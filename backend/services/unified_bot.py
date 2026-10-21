"""
Unified Bot Service - Cross-bot architecture for multi-bot support

This service provides:
- Intelligent routing between bot types
- Shared customer context across all bots
- Unified API endpoints for all bot operations
- Cross-bot analytics and reporting
"""

import json
import logging
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime, timedelta
from enum import Enum

from database import (
    get_db_context, get_user_state, set_user_state,
    get_recent_history, save_chat, get_session_info,
    search_products, list_products
)
from routing.config import DB_PATH, OLLAMA_API_URL, OLLAMA_MODEL

logger = logging.getLogger("unified_bot")

# Bot type definitions
BotType = Literal['faq', 'kb', 'customer_support', 'sales', 'general_llm']
BotStatus = Literal['active', 'learning', 'maintenance', 'disabled']

class BotPriority(Enum):
    """Priority levels for bot routing decisions"""
    URGENT = 1  # Active support tickets, urgent issues
    HIGH = 2    # Sales opportunities, returning customers
    MEDIUM = 3  # Product inquiries, general questions
    LOW = 4     # General conversation, greetings

class UnifiedBotService:
    """Main service for unified multi-bot operations"""

    def __init__(self):
        self.bot_capabilities = {
            'faq': {
                'name': 'FAQ Bot',
                'description': 'Quick answers to frequently asked questions',
                'capabilities': ['faq_lookup', 'quick_answers'],
                'priority': BotPriority.MEDIUM,
                'status': 'active'
            },
            'kb': {
                'name': 'Knowledge Base Bot',
                'description': 'Detailed product information and knowledge base',
                'capabilities': ['product_search', 'product_details', 'knowledge_retrieval'],
                'priority': BotPriority.MEDIUM,
                'status': 'active'
            },
            'customer_support': {
                'name': 'Customer Support Bot',
                'description': 'Support ticket management and human handover',
                'capabilities': ['ticket_management', 'human_handover', 'issue_resolution'],
                'priority': BotPriority.URGENT,
                'status': 'active'
            },
            'sales': {
                'name': 'Sales Bot',
                'description': 'Product recommendations and sales assistance',
                'capabilities': ['product_recommendations', 'lead_management', 'order_help'],
                'priority': BotPriority.HIGH,
                'status': 'active'
            },
            'general_llm': {
                'name': 'General AI Assistant',
                'description': 'General conversational AI for any topic',
                'capabilities': ['general_conversation', 'context_aware', 'multi_turn'],
                'priority': BotPriority.LOW,
                'status': 'active'
            }
        }

    def get_customer_context(self, wa_id: str) -> Dict[str, Any]:
        """Get comprehensive customer context across all bots"""
        try:
            with get_db_context() as conn:

                # Get user session and state
                user_state = get_user_state(wa_id)
                session_info = get_session_info(wa_id)

                # Get recent chat history across all bots
                recent_chats = conn.execute(
                    """SELECT route, message, response, created_at
                       FROM chat_history
                       WHERE wa_id = ?
                       ORDER BY created_at DESC
                       LIMIT 20""",
                    (wa_id,)
                ).fetchall()

                # Get open support tickets (when table exists)
                support_context = self._get_support_context(conn, wa_id)

                # Get sales lead info (when table exists)
                sales_context = self._get_sales_context(conn, wa_id)

                # Get product interactions
                product_interests = self._get_product_interests(conn, wa_id)

                return {
                    'wa_id': wa_id,
                    'profile': {
                        'user_state': user_state,
                        'session_info': session_info,
                        'preferred_bot': user_state.get('preferred_bot', 'auto'),
                        'language': user_state.get('lang', 'en')
                    },
                    'recent_interactions': {
                        'chat_history': [dict(row) for row in recent_chats],
                        'total_messages': len(recent_chats),
                        'last_interaction': recent_chats[0]['created_at'] if recent_chats else None
                    },
                    'support_context': support_context,
                    'sales_context': sales_context,
                    'product_interests': product_interests,
                    'routing_metadata': {
                        'last_updated': datetime.now().isoformat(),
                        'data_sources': ['user_state', 'chat_history', 'products']
                    }
                }

        except Exception as e:
            logger.error(f"Error getting customer context for {wa_id}: {e}")
            return {
                'wa_id': wa_id,
                'error': str(e),
                'profile': {},
                'recent_interactions': {},
                'support_context': {},
                'sales_context': {},
                'product_interests': {},
                'routing_metadata': {
                    'last_updated': datetime.now().isoformat(),
                    'data_sources': ['user_state', 'chat_history', 'products'],
                    'error': str(e)
                }
            }

    def _get_support_context(self, conn, wa_id: str) -> Dict[str, Any]:
        """Get support-related context (graceful fallback for missing tables)"""
        try:
            # Try to query support tickets table
            row = conn.execute(
                """SELECT status, COUNT(*) as count
                   FROM support_tickets
                   WHERE wa_id = ? AND status != 'closed'
                   GROUP BY status""",
                (wa_id,)
            ).fetchone()

            if row:
                return {
                    'has_active_tickets': True,
                    'ticket_counts': dict(row),
                    'requires_attention': row.get('open', 0) > 0
                }
        except Exception:
            # Table doesn't exist yet, return default context
            pass

        return {
            'has_active_tickets': False,
            'ticket_counts': {},
            'requires_attention': False
        }

    def _get_sales_context(self, conn, wa_id: str) -> Dict[str, Any]:
        """Get sales-related context (graceful fallback for missing tables)"""
        try:
            # Try to query sales leads table
            row = conn.execute(
                """SELECT stage, product_interest, estimated_value
                   FROM sales_leads
                   WHERE wa_id = ? AND stage != 'closed'
                   LIMIT 1""",
                (wa_id,)
            ).fetchone()

            if row:
                return {
                    'is_lead': True,
                    'stage': row.get('stage'),
                    'product_interest': row.get('product_interest'),
                    'estimated_value': row.get('estimated_value', 0)
                }
        except Exception:
            # Table doesn't exist yet, return default context
            pass

        return {
            'is_lead': False,
            'stage': None,
            'product_interest': None,
            'estimated_value': 0
        }

    def _get_product_interests(self, conn, wa_id: str) -> Dict[str, Any]:
        """Get product-related interests from chat history"""
        try:
            # Analyze recent chats for product mentions
            product_chats = conn.execute(
                """SELECT message, response, route
                   FROM chat_history
                   WHERE wa_id = ?
                   AND (message LIKE '%product%' OR message LIKE '%order%')
                   ORDER BY created_at DESC
                   LIMIT 10""",
                (wa_id,)
            ).fetchall()

            # Extract product categories mentioned
            categories_mentioned = set()
            for chat in product_chats:
                # Convert sqlite3.Row to dict
                chat_dict = dict(chat)
                message = chat_dict.get('message', '').lower()
                if 'protein' in message or 'powder' in message:
                    categories_mentioned.add('protein')
                if 'snack' in message:
                    categories_mentioned.add('snacks')
                if 'nutrition' in message:
                    categories_mentioned.add('nutrition')

            return {
                'total_product_queries': len(product_chats),
                'categories_mentioned': list(categories_mentioned),
                'last_product_query': dict(product_chats[0])['created_at'] if product_chats else None
            }
        except Exception as e:
            logger.error(f"Error getting product interests: {e}")
            return {
                'total_product_queries': 0,
                'categories_mentioned': [],
                'last_product_query': None
            }

    def route_message(self, message: str, wa_id: str, customer_context: Dict[str, Any]) -> BotType:
        """Intelligently route message to appropriate bot"""

        # Priority 1: Check for active support tickets
        if customer_context.get('support_context', {}).get('requires_attention'):
            logger.info(f"Routing {wa_id} to customer_support (active ticket)")
            return 'customer_support'

        # Priority 2: Check for sales intent
        sales_keywords = ['buy', 'price', 'cost', 'order', 'purchase', 'deal', 'discount', 'offer']
        message_lower = message.lower()
        if any(keyword in message_lower for keyword in sales_keywords):
            logger.info(f"Routing {wa_id} to sales (sales intent detected)")
            return 'sales'

        # Priority 3: Check for product-specific queries
        product_keywords = ['product', 'catalog', 'sku', 'variant', 'ingredient', 'nutrition']
        if any(keyword in message_lower for keyword in product_keywords):
            logger.info(f"Routing {wa_id} to kb (product query detected)")
            return 'kb'

        # Priority 4: Check for FAQ matches
        try:
            from database import search_faq_db
            faq_matches = search_faq_db(message, limit=3)
            if faq_matches:
                logger.info(f"Routing {wa_id} to faq (FAQ match found)")
                return 'faq'
        except Exception as e:
            logger.debug(f"FAQ search not available: {e}")

        # Priority 5: Check for general conversation patterns
        if len(message.split()) < 3 and any(word in message_lower for word in ['hi', 'hello', 'hey', 'thanks']):
            logger.info(f"Routing {wa_id} to faq (greeting)")
            return 'faq'

        # Default: Route to general LLM for complex queries
        logger.info(f"Routing {wa_id} to general_llm (default)")
        return 'general_llm'

    def process_message(self, wa_id: str, message: str, sender_name: str = None,
                       bot_type: BotType = None, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Main method to process messages through unified API"""

        try:
            # Get customer context
            customer_context = self.get_customer_context(wa_id)

            # Route to appropriate bot if not specified
            if bot_type is None:
                bot_type = self.route_message(message, wa_id, customer_context)

            # Process through specific bot
            response = self._process_through_bot(bot_type, message, wa_id, customer_context, metadata)

            # Save interaction to unified chat history
            self._save_unified_chat(wa_id, sender_name, message, response, bot_type, metadata)

            return {
                'success': True,
                'bot_type': bot_type,
                'response': response,
                'customer_context': customer_context,
                'routing_metadata': {
                    'message_timestamp': datetime.now().isoformat(),
                    'bot_used': bot_type,
                    'processing_time_ms': None  # Could add timing here
                }
            }

        except Exception as e:
            logger.error(f"Error processing message for {wa_id}: {e}")
            return {
                'success': False,
                'error': str(e),
                'bot_type': bot_type,
                'response': "I'm sorry, I encountered an error processing your request. Please try again."
            }

    def _process_through_bot(self, bot_type: BotType, message: str, wa_id: str,
                           customer_context: Dict[str, Any], metadata: Dict[str, Any] = None) -> str:
        """Process message through specific bot implementation"""

        if bot_type == 'faq':
            return self._process_faq_bot(message, wa_id, customer_context)
        elif bot_type == 'kb':
            return self._process_kb_bot(message, wa_id, customer_context)
        elif bot_type == 'customer_support':
            return self._process_support_bot(message, wa_id, customer_context)
        elif bot_type == 'sales':
            return self._process_sales_bot(message, wa_id, customer_context)
        elif bot_type == 'general_llm':
            return self._process_llm_bot(message, wa_id, customer_context)
        else:
            return "I'm not sure how to help with that. Let me connect you with a human agent."

    def _process_faq_bot(self, message: str, wa_id: str, customer_context: Dict[str, Any]) -> str:
        """Process through FAQ bot with LLM synthesis"""
        try:
            from database import search_faq_db
            faq_matches = search_faq_db(message, limit=3)

            if faq_matches:
                context = "\n\n---\n\n".join(m.get('content', '') for m in faq_matches if m.get('content'))
                # Synthesize with LLM if available
                from routing.config import GROQ_API_URL, GROQ_API_KEY, GROQ_MODEL, BRAND_NAME
                if GROQ_API_KEY and context:
                    try:
                        import requests
                        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
                        prompt = (
                            f"You are a helpful assistant for {BRAND_NAME}. "
                            f"Answer the user's question clearly, warmly, and concisely using ONLY the context below. "
                            f"Use bullet points if listing multiple items. Keep your reply between 100 and 350 words (maximum 2,500 characters) so it fits in a single WhatsApp message.\n\nContext:\n{context[:3000]}"
                        )
                        payload = {
                            "model": GROQ_MODEL,
                            "messages": [
                                {"role": "system", "content": prompt},
                                {"role": "user", "content": message}
                            ],
                            "temperature": 0.2,
                            "max_tokens": 1500
                        }
                        resp = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=15)
                        if resp.status_code == 200:
                            content = resp.json()["choices"][0]["message"]["content"].strip()
                            if content:
                                return content
                    except Exception as llm_err:
                        logger.warning(f"Unified FAQ LLM synthesis error: {llm_err}")

                best_match = faq_matches[0]
                default_text = "Here's what I found:"
                return f"💡 {best_match.get('content', default_text)}"
            else:
                return "I couldn't find a specific FAQ for that. Would you like me to search our knowledge base or connect you with support?"
        except Exception as e:
            logger.error(f"FAQ bot error: {e}")
            return "Let me help you with that through our knowledge base."

    def _process_kb_bot(self, message: str, wa_id: str, customer_context: Dict[str, Any]) -> str:
        """Process through Knowledge Base bot"""
        try:
            # Search for products (scoped to this user's tenant)
            try:
                from shared.tenancy.store import tenant_id_for_user
                tid = tenant_id_for_user(wa_id)
            except Exception:
                tid = None
            products = search_products(message, limit=3, tenant_id=tid)

            if products:
                product = products[0]
                return f"📦 {product.get('name', 'Product')} - {product.get('description', 'Available in our catalog')}. Would you like more details?"
            else:
                return "Let me search our product catalog for you. What specific product are you looking for?"
        except Exception as e:
            logger.error(f"KB bot error: {e}")
            return "I can help you find products in our catalog. What are you looking for?"

    def _process_support_bot(self, message: str, wa_id: str, customer_context: Dict[str, Any]) -> str:
        """Process through Customer Support bot"""
        support_context = customer_context.get('support_context', {})

        if support_context.get('has_active_tickets'):
            return f"I see you have an existing support ticket. Let me check the status for you. One moment while I look that up..."
        else:
            return "I'd be happy to help you with that! Let me create a support ticket and connect you with our team."

    def _process_sales_bot(self, message: str, wa_id: str, customer_context: Dict[str, Any]) -> str:
        """Process through Sales bot"""
        sales_context = customer_context.get('sales_context', {})
        product_interests = customer_context.get('product_interests', {})

        if sales_context.get('is_lead'):
            return f"Great to hear from you again! I see you're interested in {sales_context.get('product_interest', 'our products')}. Would you like me to send you some recommendations?"
        else:
            return "I'd love to help you find the perfect products! Are you looking for something specific, or would you like me to show you our popular items?"

    def _process_llm_bot(self, message: str, wa_id: str, customer_context: Dict[str, Any]) -> str:
        """Process through general LLM bot"""
        try:
            # Create context-aware prompt
            recent_context = customer_context.get('recent_interactions', {}).get('chat_history', [])[:3]
            context_summary = "Recent conversation: " + "; ".join([f"You asked about {chat.get('message', 'topics')}" for chat in recent_context])

            # For now, return a simple response (could integrate with Ollama here)
            return f"Thanks for your message! {context_summary} How can I help you further today?"

        except Exception as e:
            logger.error(f"LLM bot error: {e}")
            return "I'm here to help! Could you tell me more about what you're looking for?"

    def _save_unified_chat(self, wa_id: str, sender_name: str, message: str,
                          response: str, bot_type: BotType, metadata: Dict[str, Any] = None):
        """Save chat interaction with bot type tagging"""
        try:
            # Save with bot_type prefix for unified history
            tagged_message = f"[{bot_type}] {message}"
            save_chat(wa_id, sender_name or "Customer", tagged_message, response, route=bot_type)
        except Exception as e:
            logger.error(f"Error saving unified chat: {e}")

    def get_cross_bot_analytics(self, wa_id: str = None, time_range: int = 30) -> Dict[str, Any]:
        """Get analytics across all bot types"""
        try:
            with get_db_context() as conn:

                # Check if bot_type column exists
                column_check = conn.execute("PRAGMA table_info(chat_history)").fetchall()
                has_bot_type = any(col['name'] == 'bot_type' for col in column_check)

                if has_bot_type:
                    # Message counts by bot type
                    bot_counts = conn.execute(
                        """SELECT bot_type, COUNT(*) as count
                           FROM chat_history
                           WHERE created_at >= date('now', '-{} days')
                           GROUP BY bot_type
                           ORDER BY count DESC""".format(time_range)
                    ).fetchall()

                    bot_distribution = {row['bot_type']: row['count'] for row in bot_counts}
                    most_used_bot = bot_counts[0]['bot_type'] if bot_counts else None
                else:
                    # Fallback for legacy schema
                    bot_counts = conn.execute(
                        """SELECT SUBSTR(message, 2, INSTR(message, ']') - 2) as bot_type, COUNT(*) as count
                           FROM chat_history
                           WHERE created_at >= date('now', '-{} days')
                           AND message LIKE '[%] %'
                           GROUP BY bot_type
                           ORDER BY count DESC""".format(time_range)
                    ).fetchall()

                    bot_distribution = {row['bot_type']: row['count'] for row in bot_counts}
                    most_used_bot = bot_counts[0]['bot_type'] if bot_counts else None

                # Get total interactions
                total_msg = conn.execute(
                    """SELECT COUNT(*) as count FROM chat_history
                       WHERE created_at >= date('now', '-{} days')""".format(time_range)
                ).fetchone()

                # Active users
                active_users = conn.execute(
                    """SELECT COUNT(DISTINCT wa_id) as count FROM chat_history
                       WHERE created_at >= date('now', '-{} days')""".format(time_range)
                ).fetchone()

                return {
                    'time_range_days': time_range,
                    'total_messages': total_msg['count'] if total_msg else 0,
                    'active_users': active_users['count'] if active_users else 0,
                    'bot_distribution': bot_distribution if bot_distribution else {},
                    'most_used_bot': most_used_bot,
                    'generated_at': datetime.now().isoformat()
                }

        except Exception as e:
            logger.error(f"Error getting analytics: {e}")
            return {
                'error': str(e),
                'time_range_days': time_range,
                'total_messages': 0,
                'active_users': 0,
                'bot_distribution': {},
                'most_used_bot': None
            }

# Global service instance
unified_service = UnifiedBotService()