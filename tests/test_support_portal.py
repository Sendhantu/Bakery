from models import Message, Notification, User, db


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_customer_support_portal_stores_team_visible_live_messages(
    app_factory,
    socket_emit_spy,
):
    customer_app = app_factory("customer")
    admin_app = app_factory("admin")
    customer_client = customer_app.test_client()
    admin_client = admin_app.test_client()

    with admin_app.app_context():
        support_staff = User(
            name="Kitchen Support",
            email="kitchen-support@test.com",
            role="kitchen_staff",
            is_active=True,
        )
        support_staff.set_password("SupportPass1")
        db.session.add(support_staff)
        db.session.commit()

    assert sign_in(customer_client, "customer@test.com", "customer123").status_code == 302
    customer_response = customer_client.post(
        "/chat/send",
        data={"content": "I need help with my pickup order."},
        follow_redirects=False,
    )

    assert customer_response.status_code == 302
    assert customer_response.headers["Location"].endswith("/chat")

    with admin_app.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        first_message = Message.query.filter_by(sender_id=customer.id).first()
        assert first_message is not None
        assert first_message.content == "I need help with my pickup order."
        assert first_message.receiver.role in {"admin", "super_admin"}
        notification = Notification.query.filter_by(
            user_id=first_message.receiver_id,
            type="chat",
        ).first()
        assert notification is not None
        customer_id = customer.id

    emitted_support = [
        (payload, kwargs)
        for event, payload, kwargs in socket_emit_spy
        if event == "support_message"
    ]
    assert emitted_support
    emitted_rooms = [kwargs.get("room") for _payload, kwargs in emitted_support]
    assert "admin" in emitted_rooms
    assert f"customer_{customer_id}" in emitted_rooms

    assert (
        sign_in(admin_client, "kitchen-support@test.com", "SupportPass1").status_code
        == 302
    )
    inbox_response = admin_client.get("/admin/support")

    assert inbox_response.status_code == 200
    assert b"Customer Support" in inbox_response.data
    assert b"I need help with my pickup order." in inbox_response.data
    assert b"customer@test.com" in inbox_response.data

    thread_response = admin_client.get(f"/admin/chat/{customer_id}")

    assert thread_response.status_code == 200
    assert b"Reply as Kitchen Support" in thread_response.data
    with admin_app.app_context():
        assert Message.query.filter_by(
            sender_id=customer_id,
            is_read=False,
        ).count() == 0

    reply_response = admin_client.post(
        f"/admin/chat/send/{customer_id}",
        data={"content": "We can help from the counter."},
        follow_redirects=False,
    )

    assert reply_response.status_code == 302
    assert reply_response.headers["Location"].endswith(f"/admin/chat/{customer_id}")
    with admin_app.app_context():
        reply = Message.query.filter_by(
            receiver_id=customer_id,
            content="We can help from the counter.",
        ).first()
        assert reply is not None
        assert reply.sender.email == "kitchen-support@test.com"

    customer_chat = customer_client.get("/chat")

    assert customer_chat.status_code == 200
    assert b"I need help with my pickup order." in customer_chat.data
    assert b"We can help from the counter." in customer_chat.data
