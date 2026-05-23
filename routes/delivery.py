from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort, jsonify
from flask_login import login_required, current_user
from bootstrap import get_container
from exceptions import ValidationError
from functools import wraps
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from models import db, Delivery, DeliveryAgent, Order, User, can_transition_order_status, get_allowed_order_statuses
from datetime import datetime

delivery_bp = Blueprint('delivery', __name__)


@delivery_bp.before_request
def ensure_delivery_portal():
    if current_app.config.get('PORTAL_ROLE') != 'delivery':
        if current_user.is_authenticated and current_user.role == 'delivery':
            from routes.auth import portal_url_for_role
            return redirect(portal_url_for_role('delivery', url_for('delivery.dashboard')))
        abort(404)

def delivery_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'delivery':
            flash('Access denied.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def get_current_delivery_agent():
    return DeliveryAgent.query.filter_by(user_id=current_user.id).first()


def get_assigned_delivery_or_404(order_id):
    agent = get_current_delivery_agent()
    if agent is None:
        abort(404)

    delivery = Delivery.query.filter_by(order_id=order_id, agent_id=agent.id).first()
    if delivery is None or delivery.order is None:
        abort(404)

    return agent, delivery, delivery.order


def get_delivery_dashboard_context():
    agent = get_current_delivery_agent()
    assigned = []
    delivered_today = 0
    completed_count = 0
    if agent:
        assigned = Delivery.query.filter_by(agent_id=agent.id)\
                     .filter(Delivery.status != 'DELIVERED')\
                     .order_by(Delivery.assigned_time.desc()).all()
        for delivery in assigned:
            if delivery.order:
                delivery.allowed_statuses = get_allowed_order_statuses(
                    delivery.order.status,
                    actor='delivery',
                )
        completed_count = Delivery.query.filter_by(agent_id=agent.id, status='DELIVERED').count()
        delivered_today = Delivery.query.filter_by(agent_id=agent.id, status='DELIVERED').filter(
            db.func.date(Delivery.delivered_time) == datetime.utcnow().date()
        ).count()
    return dict(
        agent=agent,
        assigned=assigned,
        assigned_count=len(assigned),
        completed_count=completed_count,
        delivered_today=delivered_today,
    )


@delivery_bp.route('/')
@delivery_required
def dashboard():
    context = get_delivery_dashboard_context()
    if not context['agent'] and current_user.role == 'delivery':
        flash('No delivery agent profile found.', 'warning')
    return render_template('delivery/dashboard.html', **context)


@delivery_bp.route('/live/dashboard')
@delivery_required
def dashboard_live():
    context = get_delivery_dashboard_context()
    return jsonify({
        'fragments': {
            '#delivery-agent-status': render_template('delivery/_dashboard_status.html', **context),
            '#delivery-dashboard-live': render_template('delivery/_dashboard_live.html', **context),
        }
    })


@delivery_bp.route('/order/<int:order_id>')
@delivery_required
def order_detail(order_id):
    _agent, delivery, order = get_assigned_delivery_or_404(order_id)
    items = order.items.all()
    return render_template('delivery/order_detail.html',
                           order=order, items=items, delivery=delivery,
                           allowed_statuses=get_allowed_order_statuses(order.status, actor='delivery'))


@delivery_bp.route('/order/<int:order_id>/update', methods=['POST'])
@delivery_required
def update_status(order_id):
    agent, delivery, order = get_assigned_delivery_or_404(order_id)
    status = (request.form.get('status') or '').strip().upper()
    # optimistic version check if client provided expected_version
    expected_version = request.form.get('expected_version')
    if expected_version is not None:
        from utils.optimistic import assert_version

        try:
            assert_version(order, expected_version, entity_name='Order')
        except Exception as exc:
            flash('Version conflict: this order has been updated by someone else.', 'danger')
            return redirect(url_for('delivery.order_detail', order_id=order_id))

    offline_sync = get_container().offline_sync_service
    if offline_sync.enabled and not offline_sync.is_online():
        snapshot = offline_sync.get_snapshot("orders", order_id) or {}
        request_id = offline_sync.queue_order_status_update_by_id(
            order_id,
            status,
            actor_id=current_user.id,
            expected_version=snapshot.get("version"),
            snapshot_payload={**snapshot, "id": order_id, "status": status},
        )
        flash(
            f'Offline mode: update queued for sync ({request_id[:8]}).',
            'warning',
        )
        return redirect(url_for('delivery.order_detail', order_id=order_id))
    try:
        order = get_container().order_service.update_order_status(
            order_id,
            status,
            actor='delivery',
            actor_id=current_user.id,
        )
    except ValidationError:
        flash('Invalid delivery status.', 'danger')
        return redirect(url_for('delivery.order_detail', order_id=order_id))
    except SQLAlchemyError:
        db.session.rollback()
        offline_sync = get_container().offline_sync_service
        snapshot = offline_sync.get_snapshot("orders", order_id) or {}
        request_id = offline_sync.queue_order_status_update_by_id(
            order_id,
            status,
            actor_id=current_user.id,
            expected_version=snapshot.get("version"),
            snapshot_payload={**snapshot, "id": order_id, "status": status},
        )
        flash(
            f'Connection lost. Delivery update queued locally for sync ({request_id[:8]}).',
            'warning',
        )
        return redirect(url_for('delivery.order_detail', order_id=order_id))

    get_container().offline_sync_service.cache_order(order)

    flash(f'Status updated to {status}.', 'success')
    return redirect(url_for('delivery.order_detail', order_id=order.id))


@delivery_bp.route('/order/<int:order_id>/collect-payment', methods=['POST'])
@delivery_required
def collect_payment(order_id):
    _agent, _delivery, order = get_assigned_delivery_or_404(order_id)
    offline_sync = get_container().offline_sync_service
    expected_version = request.form.get('expected_version')
    if expected_version is not None:
        from utils.optimistic import assert_version

        try:
            assert_version(order, expected_version, entity_name='Order')
        except Exception:
            flash('Version conflict: this order has been updated by someone else.', 'danger')
            return redirect(url_for('delivery.order_detail', order_id=order_id))
    if offline_sync.enabled and not offline_sync.is_online():
        snapshot = offline_sync.get_snapshot("orders", order_id) or {}
        request_id = offline_sync.queue_cod_collection_by_id(
            order_id,
            request.form.get('amount_received'),
            request.form.get('payment_mode', 'CASH'),
            actor_id=current_user.id,
            expected_version=snapshot.get("version"),
            snapshot_payload={**snapshot, "id": order_id, "payment_status": "PAID"},
        )
        flash(
            f'Offline mode: COD collection queued for sync ({request_id[:8]}).',
            'warning',
        )
        return redirect(url_for('delivery.order_detail', order_id=order_id))
    try:
        order = get_container().delivery_service.collect_cod_payment(
            order_id,
            request.form.get('amount_received'),
            payment_mode=request.form.get('payment_mode', 'CASH'),
            actor_id=current_user.id,
            expected_version=expected_version,
        )
    except ValidationError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('delivery.order_detail', order_id=order_id))
    except SQLAlchemyError:
        db.session.rollback()
        offline_sync = get_container().offline_sync_service
        snapshot = offline_sync.get_snapshot("orders", order_id) or {}
        request_id = offline_sync.queue_cod_collection_by_id(
            order_id,
            request.form.get('amount_received'),
            request.form.get('payment_mode', 'CASH'),
            actor_id=current_user.id,
            expected_version=snapshot.get("version"),
            snapshot_payload={**snapshot, "id": order_id, "payment_status": "PAID"},
        )
        flash(
            f'Connection lost. COD collection queued locally for sync ({request_id[:8]}).',
            'warning',
        )
        return redirect(url_for('delivery.order_detail', order_id=order_id))

    get_container().offline_sync_service.cache_order(order)

    flash('COD payment marked as collected.', 'success')
    return redirect(url_for('delivery.order_detail', order_id=order.id))


@delivery_bp.route('/history')
@delivery_required
def history():
    agent = DeliveryAgent.query.filter_by(user_id=current_user.id).first()
    deliveries = []
    status = (request.args.get('status') or '').strip().upper()
    search = (request.args.get('q') or '').strip()
    if agent:
        query = Delivery.query.filter_by(agent_id=agent.id).join(Order, Delivery.order_id == Order.id).join(
            User, Order.user_id == User.id
        )
        if status and status in {'ASSIGNED', 'PACKED', 'OUT_FOR_DELIVERY', 'DELIVERED', 'ON_HOLD'}:
            query = query.filter(Delivery.status == status)
        if search:
            like = f'%{search}%'
            query = query.filter(or_(
                Order.order_number.ilike(like),
                Order.phone.ilike(like),
                Order.city.ilike(like),
                User.name.ilike(like),
            ))
        deliveries = query.order_by(Delivery.assigned_time.desc()).all()
    return render_template(
        'delivery/history.html',
        deliveries=deliveries,
        selected_status=status,
        search_query=search,
        status_options=['ASSIGNED', 'PACKED', 'OUT_FOR_DELIVERY', 'DELIVERED', 'ON_HOLD'],
    )
