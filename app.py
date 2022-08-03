import os
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError, LineBotApiError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)
from scenario.scenario_manager import ScenarioManager

app = Flask(__name__)

# Instantiate scenario manager
line_bot_api = LineBotApi(os.environ['LINEMESSAGING_CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['LINEMESSAGING_CHANNEL_SECRET'])
scenario_manager = ScenarioManager(line_bot_api)


@app.route('/')
def index():
   print('Request for index page received')
   return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/hello', methods=['POST'])
def hello():
   name = request.form.get('name')

   if name:
       print('Request for hello page received with name=%s' % name)
       return render_template('hello.html', name = name)
   else:
       print('Request for hello page received with no name or blank name -- redirecting')
       return redirect(url_for('index'))

@app.route('/callback', methods=['POST'])
def callback():
    return_value = None
    return_value = webhook_callback(request)
    return return_value

def webhook_callback(request):
    """The LINE webhook event handler.
    It receives events from the LINE messaging API, such as text messages or postback actions.
    The entry point for the chatbot system.
    """

    try:
        # get X-Line-Signature header value
        signature = request.headers['X-Line-Signature']

        # get request body as text
        body = request.get_data(as_text=True)

        # handle webhook body
        handler.handle(body, signature)
    except (InvalidSignatureError, KeyError):
        print("Invalid signature. Please check your channel access token/channel secret.")
    except LineBotApiError as line_api_error:
        print(str(line_api_error))

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=event.message.text))

if __name__ == '__main__':
   app.run()