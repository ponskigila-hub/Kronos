"""
Thin platform adapters. None of these contain business logic -- they only
translate platform events into StockAssistant.handle_message(user_id, text)
calls and format the response back into whatever that platform expects.
"""
