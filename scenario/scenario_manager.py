from linebot.exceptions import LineBotApiError
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)
class ScenarioException(Exception):
    """Custom exception class for scenario module.
    """

class ScenarioManager():
    def __init__(self, line_bot_api):

        self.line_bot_api = line_bot_api

    def handle_line_webhook_event(self, event, event_type):
        reply_messages = []
        reply_messages.append(TextSendMessage(text="こんばんは"))
        reply_messages.append(TextSendMessage(text="こんばんは～"))

        return reply_messages

