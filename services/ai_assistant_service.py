import json
from datetime import timedelta

import requests

from clock import utcnow
from models import Message, Notification, Product, User, db


AI_SUPPORT_EMAIL = "ai-assistant@bakery.local"


class AIAssistantService:
    def __init__(self, config=None, context_service=None):
        self.config = config or {}
        self.context_service = context_service

    def _extract_product_names(self, text):
        words = (text or "").split()
        candidates = []
        product_keywords = {
            "cake",
            "cakes",
            "pastry",
            "pastries",
            "bread",
            "breads",
            "brownie",
            "brownies",
            "cookies",
            "cookie",
            "cupcake",
            "cupcakes",
            "donut",
            "donuts",
            "pastry",
            "cookies",
        }
        for index, word in enumerate(words):
            base = word.strip(".,;:!?()[]\"").lower()
            if base in product_keywords:
                start = max(0, index - 3)
                segment = " ".join(words[start:index + 1]).strip(" ,;:!?()[]\".")
                candidates.append(segment[:80])
        return candidates

    def _enabled(self):
        return bool(self.config.get("AI_ASSISTANT_ENABLED", False))

    def _ollama_url(self):
        base_url = (self.config.get("OLLAMA_BASE_URL") or "").strip().rstrip("/")
        return f"{base_url}/api/generate" if base_url else ""

    def _model_name(self):
        return (self.config.get("OLLAMA_MODEL") or "llama3.1").strip()

    def _generate_with_ollama(self, prompt):
        if not self._enabled():
            return None

        url = self._ollama_url()
        model = self._model_name()
        if not url or not model:
            return None

        timeout = float(self.config.get("OLLAMA_TIMEOUT_SECONDS") or 3)
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.25,
                "num_predict": 220,
            },
        }
        try:
            response = requests.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None

        text = (data.get("response") or "").strip()
        return text[:1600] if text else None

    def _conversation_summary(self, history):
        turns = history or []
        lines = []
        for turn in turns[-10:]:
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                lines.append(f"{role}: {content[:300]}")
        if not lines:
            return "(no prior conversation)"
        return "\n".join(lines)

    def _prompt(self, customer_request, context, history=None):
        compact_context = json.dumps(context, ensure_ascii=True, default=str)[:12000]
        return f"""
You are SweetCrumbs Bakery's customer assistant.
Use only the provided bakery context. Do not invent product availability, prices,
order status, delivery promises, medical/allergen guarantees, discounts, or payment
confirmation. If the customer wants to place an order, suggest products and ask them
to add items to cart and complete checkout.

Recent conversation:
{self._conversation_summary(history)}

Answer warmly in 2-5 short sentences. If useful, mention 1-3 exact product names
from product_candidates or checkout_addons.

Bakery context JSON:
{compact_context}

Customer request:
{customer_request}
""".strip()

    def _fallback_answer(self, customer_request, context, history=None):
        query = (customer_request or "").lower()
        products = context.get("product_candidates") or []
        orders = context.get("recent_orders") or []
        addons = context.get("checkout_addons") or []

        if "order" in query and orders:
            latest = orders[0]
            return (
                f"Your latest order {latest['order_number']} is currently "
                f"{latest['status'].replace('_', ' ').title()}. "
                "If you need a change, message the support team from this chat."
            )

        if products:
            names = ", ".join(product["name"] for product in products[:3])
            message = context.get("recommendation_message") or "I found a few good matches."
            if addons:
                message += f" You can also add {addons[0]['name']} at checkout."
            return f"{message} Good matches: {names}."

        if history:
            prior_names = []
            for turn in history[-10:]:
                if turn.get("role") == "assistant" and turn.get("content"):
                    for name in self._extract_product_names(turn["content"]):
                        if name not in prior_names:
                            prior_names.append(name)
            if prior_names:
                return (
                    f"I did not find new matches for that. Earlier I mentioned "
                    f"{', '.join(prior_names[:3])}. Try asking for an occasion, "
                    "budget, flavour, or eggless preference."
                )

        return (
            "I can help you search cakes, breads, pastries, gifts, and party add-ons. "
            "Try asking for an occasion, budget, flavour, or eggless preference."
        )

    def answer_customer_request(self, user_id, customer_request, *, limit=None, history=None):
        limit = int(limit or self.config.get("AI_CONTEXT_PRODUCT_LIMIT") or 8)
        context = self.context_service.safe_build_customer_context(
            user_id=user_id,
            query_text=customer_request,
            limit=limit,
            history=history,
        )
        prompt = self._prompt(customer_request, context, history=history)
        ai_text = self._generate_with_ollama(prompt)
        message = ai_text or self._fallback_answer(customer_request, context, history=history)
        return {
            "ok": True,
            "source": "ollama" if ai_text else "rules",
            "model": self._model_name() if ai_text else "rule-based fallback",
            "message": message,
            "products": (context.get("product_candidates") or [])[:limit],
            "checkout_addons": context.get("checkout_addons") or [],
            "context_tools": context.get("tools") or [],
        }

    def ensure_support_bot(self):
        bot = User.query.filter_by(email=AI_SUPPORT_EMAIL).first()
        if bot:
            bot.is_active = True
            bot.role = "kitchen_staff"
            bot.email_locked = True
            return bot

        bot = User(
            name="SweetCrumbs AI Assistant",
            email=AI_SUPPORT_EMAIL,
            role="kitchen_staff",
            is_active=True,
            email_locked=True,
        )
        db.session.add(bot)
        db.session.flush()
        return bot

    def store_support_exchange(self, customer_id, customer_text, assistant_text):
        if (
            not customer_id
            or not self.config.get("AI_SUPPORT_BOT_ENABLED", False)
            or not customer_text
            or not assistant_text
        ):
            return []

        bot = self.ensure_support_bot()
        customer_message = Message(
            sender_id=customer_id,
            receiver_id=bot.id,
            content=customer_text,
        )
        bot_message = Message(
            sender_id=bot.id,
            receiver_id=customer_id,
            content=assistant_text,
        )
        db.session.add_all([customer_message, bot_message])
        return [customer_message, bot_message]

    def maybe_create_recommendation_notification(self, user_id, viewed_product):
        if (
            not user_id
            or not viewed_product
            or not self.config.get("AI_PUSH_RECOMMENDATIONS_ENABLED", False)
        ):
            return None

        products, _message = self.context_service.search_products(
            viewed_product.name,
            user_id=user_id,
            limit=4,
        )
        candidate = next(
            (product for product in products if product.id != viewed_product.id),
            None,
        )
        if candidate is None:
            candidate = (
                Product.query.filter(
                    Product.is_active.is_(True),
                    Product.id != viewed_product.id,
                    Product.category_id == viewed_product.category_id,
                )
                .order_by(Product.is_featured.desc(), Product.created_at.desc())
                .first()
            )
        if candidate is None:
            return None

        link = f"/product/{candidate.id}"
        recent_cutoff = utcnow() - timedelta(hours=6)
        existing = Notification.query.filter(
            Notification.user_id == user_id,
            Notification.type == "recommendation",
            Notification.link == link,
            Notification.created_at >= recent_cutoff,
        ).first()
        if existing:
            return None

        notification = Notification(
            user_id=user_id,
            title="Recommended for you",
            message=f"Since you viewed {viewed_product.name}, you may like {candidate.name}.",
            type="recommendation",
            priority="normal",
            link=link,
        )
        db.session.add(notification)
        return notification
