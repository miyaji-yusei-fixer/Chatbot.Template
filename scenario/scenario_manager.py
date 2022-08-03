from linebot.exceptions import LineBotApiError

class ScenarioException(Exception):
    """Custom exception class for scenario module.
    """

class ScenarioManager():
    def __init__(self, line_bot_api):

        self.line_bot_api = line_bot_api

    def handle_line_webhook_event(self, event, event_type):
        reply_messages = []

        # Store event source data
        self.event_source = event.source

        # Refresh user session
        self.user_session.getUserSession(
            self.event_source.user_id
        )

        # Setup scenario language
        self.setupScenarioLanguage()

        # First, check if a special flow will handle the event
        messages = flow_manager.handle_line_webhook_event(event, event_type)

        if not messages:
            # Event was not handled by a special flow
            # Switch to default behaviour
            messages = self._handle_webhook_event_default(event, event_type)

        add_to_list(reply_messages, messages)

        return reply_messages

    def _handle_webhook_event_default(self, event, event_type):
        # Default behaviour only handles postback and text message events
        # If postback, try to find a message with an ID that matches the data
        # If text message, check the user text mapping item in the DB for a match
        self.scenario_settings = self.__getEnvironmentSettings__()

        # Scenario is activeScenario#version
        if self.scenario_settings:
            scenario_id = self.scenario_settings["activeScenarioId"]
            version = self.scenario_settings["envMapping"][SCENARIO_ENVIRONMENT]
            self.scenario = scenario_id + "#" + version
            self.__setupTextMapping__()

            scenario_object = self.__getScenario__(scenario_id)
            if scenario_object:
                self.scenario_version_object = scenario_object[0]["versions"][version]
        else:
            self.scenario = "default"

        message = None

        if event_type == 'postback':
            message = self.getMessageById(event.postback.data)

            if not message\
            and 'CONGESTION_SITUATION' in event.postback.data:
                message = self.__getCongestionSituationScenarioData__(event.postback.data)
            if not message\
            and 'CHAT_MODE_START' in event.postback.data:
                message = self.__chat_mode_start__(event)

        elif event_type == 'text_message':
            message = self.getMessageByText(event.message.text)

            # In the case of text message, if no mapping is found,
            # return the default message for trash scenario, if available.
            # if not message\
            # and event.message.text == self.scenario_settings['publicityPaperKeyword']:
            #     message = self.__getPublicityPaperScenarioData__()
            if not message:
                message = self.__getPublicityPaperScenarioData__(event.message.text)
            if not message:
                message = self.__getCongestionSituationSelectScenarioData__(event.message.text)
            if not message:
                message = self._trash_separation_fuzzy_search(event.message.text)

        # If the default handler returned a message, deactivate current special flow
        if message:
            self.user_session.setSpecialFlow(
                event.source.user_id,
                None
            )

        return message

    def getMessageById(self, message_id):
        """Retrieves a message from the scenario saved in the database
        to sent as a reply.

        :param str messageId: The message unique identifier
        :returns linebot.models.Message: A list of or single LINE Messaging API message object.
        """
        reply_messages = None

        if "apiCall" in message_id:
            # Convert messageId data to dictionary
            params_list = message_id.split("&")
            param_dict = {}
            for param in params_list:
                key = param.split("=")[0]
                value = param.split("=")[1]
                param_dict[key] = value

            param_dict['user_id'] = self.event_source.user_id
            param_dict['scenario'] = self.scenario

            api_call_id = param_dict.get("apiCall")

            message_data = self.__getScenarioData__(self.scenario, api_call_id)

            message_data["parameters"] = param_dict

            reply_messages = self.__generateMessage__(message_data)

        else:
            message_data = self.__getScenarioData__(self.scenario, message_id)

            if message_data:
                reply_messages = self.__generateMessage__(message_data)
            elif self.language_code:
                # Target message might be non-translatable (composite message or similar)
                base_scenario = self.__getBaseScenarioPartition__()
                message_data = self.__getScenarioData__(base_scenario, message_id)

                if message_data:
                    reply_messages = self.__generateMessage__(message_data)

        if reply_messages:
            # Save latest reply message ID in user
            # session table before sending it via LINE Messaging API
            if self.event_source:
                self.user_session.setLastMessageId(
                    self.event_source.user_id,
                    message_id)

        return reply_messages

    def __generateMessage__(self, message_data):
        """Creates the actual message object using the LINE SDK.
        :param dict message_data: JSON like dict representing a LINE API message
        :returns linebot.models.Message: A list of or single LINE Messaging API message object.
        """

        alttext_support = [
            "buttons", "imagemap", "carousel", "bubbleFlex", "carouselFlex", "confirm"
        ]

        messages = None

        # Check if composite message
        if message_data[0]["dataType"] == "compositeMessage":
            message_list = message_data[0]["messages"]
            if message_list:
                items = []
                for message_id in message_list[:5]:
                    msg_data = self.__getScenarioData__(self.scenario, message_id)
                    if msg_data:
                        items.append(msg_data)
                self.main_message_data_id = message_data[0]["dataId"]
                reply_msgs = []
                for item in items:
                    # Ignore types that do not have a generator
                    item_data_type = item[0]["dataType"]
                    if item_data_type in self.message_generator:
                        if item_data_type in alttext_support and item[0]["nameLBD"]:
                            reply_msgs.append(
                                self.message_generator[item_data_type](item[0]["params"],
                                                                       item[0]["nameLBD"])
                            )
                        else:
                            reply_msgs.append(
                                self.message_generator[item_data_type](item[0]["params"])
                            )

                messages = reply_msgs
        elif message_data[0]["dataType"] == "apiCall":
            # Get api call data
            function_name = message_data[0]["function"]
            params = message_data[0]["parameters"]
            params['SCENARIO_ENVIRONMENT'] = SCENARIO_ENVIRONMENT

            return self.chatbot_api.call_api_method(function_name, self.event_source, params)

        else:
            if (message_data[0].get("params") and message_data[0].get("dataType") in alttext_support) \
            and message_data[0].get("nameLBD"):
                messages = self.message_generator[message_data[0]["dataType"]](
                    message_data[0]["params"], message_data[0]["nameLBD"])
            else:
                messages = self.message_generator[message_data[0]["dataType"]]\
                    (message_data[0]["params"])

        if messages and message_data[0].get("quickReply"):
            quick_reply_message = quickreply_message.generate(message_data[0].get("quickReply"))
            messages.quick_reply = quick_reply_message

        return messages

    def getMessageByText(self, text):
        """Retrieves a message from the scenario by user defined text mapping.

        If no exact match is found, use fuzzy search to try and match the best possible result.

        :param str text: The text message received as an event from the webhook.
        :returns linebot.models.Message: A list of or a single LINE Messaging API message object.
        """
        message = None

        if self.text_mapping:
            message_id = self.text_mapping.get(text)
            if message_id:
                message = self.getMessageById(message_id)

        return message

    def setupScenarioLanguage(self):
        """Sets up the scenario language for the current execution of the chatbot,
        based on the user settings saved in the session table.
        """
        # Get and set user language from user session table. eventSource has LINE user ID
        lang_code = self.user_session.getUserLanguage(
            self.event_source.user_id
        )

        # If langCode is not empty, non-Japanese language
        # In case it's Japanese, it's already been set up during init
        if lang_code:
            self.language_code = lang_code
            self.scenario = self.scenario + "#" + lang_code
            self.__setupTextMapping__()

    def __generate_flex_message_helper__(self, carousel_data, name_lbd="カルーセルフレックス", scenario=None):
        bubble_messages = []
        bubbles = carousel_data['bubbleParam']
        #bubble limit is 10
        limit = 10
        for index, bbl in enumerate(bubbles):
            if index == limit:
                break
            bubble_data = self.__getScenarioData__((scenario or self.scenario), bbl)
            if bubble_data:
                bubble_messages.append(bubble_data)

        return flex_message.generate_carousel(bubble_messages, name_lbd)

    # Set up text mapping based on current scenario
    def __setupTextMapping__(self):
        mapping_data_list = self.__getScenarioDataByType__(self.scenario, "textMapping")
        if len(mapping_data_list) > 0:
            self.text_mapping = mapping_data_list[0].get("textMapping")
        elif self.language_code:
            # Fallback to default
            base_scenario = self.__getBaseScenarioPartition__()
            mapping_data_list = self.__getScenarioDataByType__(base_scenario, "textMapping")

            if len(mapping_data_list) > 0:
                self.text_mapping = mapping_data_list[0].get("textMapping")

    @staticmethod
    def __getEnvironmentSettings__():
        cosmosdb_scenario = cosmos_client.get_container_scenario(TABLE_CHATBOT_SCENARIO, '/scenarioId')
        try:
            for item in cosmosdb_scenario.query_items(
                query="SELECT * FROM r WHERE r.scenarioId=@scenarioId",
                    parameters=[
                        { "name":"@scenarioId", "value": "settings" }
                    ],
                enable_cross_partition_query=True):
                return item
            return None

        except exceptions.CosmosHttpResponseError:
            # No data found
            return None

    @staticmethod
    def __getScenario__(scenario_id):
        cosmosdb_scenario = cosmos_client.get_container_scenario(TABLE_CHATBOT_SCENARIO, '/scenarioId')
        try:
            response = list(cosmosdb_scenario.query_items(
                query="SELECT * FROM r WHERE r.scenarioId=@scenarioId",
                    parameters=[
                        { "name":"@scenarioId", "value": scenario_id }
                    ],
                partition_key=scenario_id,
                enable_cross_partition_query=True
            ))
            return replace_decimals(response)

        except exceptions.CosmosHttpResponseError:
            # No data found
            return None

    def __getScenarioData__(self, scenario, data_id):
        cosmosdb_scenario_data = cosmos_client.get_container_scenario(TABLE_CHATBOT_SCENARIO_DATA, '/scenario')
        try:
            response = list(cosmosdb_scenario_data.query_items(
                query="SELECT * FROM r WHERE r.scenario=@scenario AND r.dataId=@dataId",
                    parameters=[
                        { "name":"@scenario", "value": scenario },
                        { "name":"@dataId", "value": data_id }
                    ],
                partition_key=scenario,
                enable_cross_partition_query=True
            ))
            self.main_message_data_id = data_id
            return replace_decimals(response)

        except exceptions.CosmosHttpResponseError:
            # No data found
            return None

    @staticmethod
    def __getScenarioDataByType__(scenario, data_type):
        cosmosdb_scenario_data = cosmos_client.get_container_scenario(TABLE_CHATBOT_SCENARIO_DATA, '/scenario')
        try:
            response = list(cosmosdb_scenario_data.query_items(
                query="SELECT * FROM r WHERE r.scenario=@scenario AND r.dataType=@dataType",
                    parameters=[
                        { "name":"@scenario", "value": scenario },
                        { "name":"@dataType", "value": data_type }
                    ],
                partition_key=scenario,
                enable_cross_partition_query=True
            ))

            return replace_decimals(response)

        except exceptions.CosmosHttpResponseError:
            # No data found
            return []

    # Aux method to get the non-locale scenario partion (scenarioId + version)
    def __getBaseScenarioPartition__(self):
        scenario_split = self.scenario.split("#")
        return scenario_split[0] + "#" + scenario_split[1]

    def getUserSession(self):
        """Gets the user session data.

        :returns dict: The user session data in JSON style dict
        """
        return self.user_session.getUserSession(self.event_source.user_id)

    #####################
    ### LOCATION ###
    #####################
    def startLocationScenario(self):
        """Starts the special location scenario.

        returns linebot.models.Message: The first message of the location scenario.
        """
        self.user_session.setStartLocation(self.event_source.user_id)
        return self.getMessageById("LOCA_LOCATION_CONFIRM")

    def stopLocationScenario(self):
        """Disables location scenario by deleting data from the
        user session table.
        """
        self.user_session.delLocaton(self.event_source.user_id)
        return ""

    def handleLocationMessage(self, message):
        """Handles a LINE webhook location event (not damage report).

        :param message: Location message from LINE API webhook
        :type message: linebot.models.LocationMessage
        """
        message_id = self.location.process_location_message(
            message,
            self.event_source.user_id
        )

        return_value = None

        if message_id:
            return_value = self.getMessageById(message_id)\
                           if isinstance(message_id, str) else message_id

        return return_value

    ######################
    ## TRASH SEPARATION ##
    ######################
    def _trash_separation_fuzzy_search(self, user_input):
        """Checks if trash separation scenario exists.
        If it does, try a fuzzy search.
        If not message is found, then return a default message for the scenario.

        :param str scenario: The scenario identifier
        :return linebot.models.Message: A text message or None if trash scenario does not exist.
        """
        message = None

        # Check if the trash talk object exists
        trash_talk = self.__getScenarioData__(self.scenario, "TRASH_SEPARATION_TALK")

        if trash_talk:
            # Fuzzy search
            best_matches = fuzzy_search(
                user_input,
                list(self.text_mapping)
            )

            if best_matches is not None:
                # if len(best_matches) <= 4:
                #     data = {
                #         'text': 'どんな情報をお探しですか？',
                #         'actionCount': len(best_matches)
                #     }
                #     for i, best_match in enumerate(best_matches):
                #         data['actions.' + str(i)] = {
                #             'type': 'message',
                #             'label': best_match,
                #             'text': best_match
                #         }
                #     message = self.message_generator['buttons'](data)
                # else:
                    bubble_messages = []
                    column_count  = -(-len(best_matches) // 4)
                    items = best_matches
                    i = 0
                    while i + 1 <= column_count:
                        params = {
                            'type': 'bubble',
                            "header": {
                                "type": "box",
                                "layout": "vertical",
                                "contents": [{
                                    "type": "text",
                                    "text": "どんな情報をお探しですか？",
                                    "align": "start",
                                    "contents": []
                                }]
                            },
                            'body': {
                                'type': 'box',
                                'layout': 'vertical',
                                'contents': [],
                                "paddingTop": "none"
                            }
                        }
                        for j, item in enumerate(items):
                            if j >= 4:
                                break
                            params['body']['contents'].append({
                                "type": "button",
                                "action": {
                                    'type': 'message',
                                    'label': item,
                                    'text': item
                                }
                            })
                        bubble_messages.append({
                            'params': params
                        })
                        items = items[4:]
                        i += 1

                    message = flex_message.generate_carousel(
                        bubble_messages,
                        'どんな情報をお探しですか？'
                    )

            else:
                # Return default message
                default_id = self.text_mapping.get("TRASH_NOT_FOUND_DEFAULT_MESSAGE")
                message = self.getMessageById(default_id)

        return message

    ###########
    ## BOSAI ##
    ###########
    def _bosai_set_mode(self, activated=True):
        # Update bosai mode status on the scenario table
        # Check existing settings
        bosai_settings = self.scenario_settings.get('bosaiMode')
        if not bosai_settings:
            bosai_settings = {}

        bosai_settings[SCENARIO_ENVIRONMENT] = activated

        # Update container

        container = cosmos_client.get_container_scenario(TABLE_CHATBOT_SCENARIO, '/scenarioId')

        upsert_item = cosmos_client.get_scenario(container, "settings")
        upsert_item['bosaiMode'] = bosai_settings

        container.upsert_item(
            upsert_item
        )

    def bosai_mode(self, activate=True):
        """Activates or deactivates bosai mode.

        Enabling bosai mode consists of 3 steps:
        1. Changing the active rich menu to the one set as bosai mode rich menu.
        2. Broadcast the first message of the bosai special flow
        3. Set a flag in settings indicating bosai mode status

        :param bool: Activation flag
        :returns str result: "SUCCESS" or "ERROR"
        :return [T <= str] warnings: List of warnings or errors, if any ocurred.
        """
        result = 'SUCCESS'
        message = ''

        self.scenario_settings = self.__getEnvironmentSettings__()

        # Activate or deactivate bosai mode
        # Check if message and rich menu settings exist
        try:
            msg_to_broadcast = self.getMessageById(BOSAI_FLOW_START)

            # Depending on the environment, get production or sandbox
            if not self.scenario_settings.get('richMenus'):
                # No rich menu is set, so raise an exception.
                raise ScenarioException('通常モードと災害時モードのリッチメニュー設定が見つかりませんでした。'
                                        'シナリオモジュールのリッチメニュー管理画面で設定してください。')

            if SCENARIO_ENVIRONMENT == 'production':
                normal_rich_menu_id = self.scenario_settings.get('richMenus').get('defaultProduction')
                bosai_rich_menu_id = self.scenario_settings.get('richMenus').get('bosaiProduction')
            else:
                normal_rich_menu_id = self.scenario_settings.get('richMenus').get('defaultSandbox')
                bosai_rich_menu_id = self.scenario_settings.get('richMenus').get('bosaiSandbox')

            if activate and (not msg_to_broadcast or not bosai_rich_menu_id):
                raise ScenarioException('災害時モードは有効にできません。 リッチメニュー設定がないか、シナリオが正しく作成されていません。')

            # Rich menu switch and broadcast
            if activate:
                self.line_bot_api.broadcast(
                    msg_to_broadcast
                )
                self.line_bot_api.set_default_rich_menu(bosai_rich_menu_id)
            else:
                # Go back to normal mode
                msg_normal_mode = self.getMessageById(
                    BACK_TO_NORMAL_MODE
                )

                if msg_normal_mode:
                    self.line_bot_api.broadcast(
                        msg_normal_mode
                    )

                if normal_rich_menu_id:
                    self.line_bot_api.set_default_rich_menu(normal_rich_menu_id)
                else:
                    self.line_bot_api.cancel_default_rich_menu()

            self._bosai_set_mode(activate)
        except (ScenarioException, LineBotApiError) as scenario_error:
            logging.exception('災害モードのアクティブ化中にエラーが発生しました。')
            result = 'ERROR'
            message = str(scenario_error)

        return result, message

    # 広報誌用関数
    def __getPublicityPaperScenarioData__(self, publicity_paper_keyword=None):
        cosmosdb_scenario_data = cosmos_client.get_container_scenario(TABLE_CHATBOT_SCENARIO_DATA, '/scenario')
        try:
            query = "SELECT * FROM r WHERE r.scenario='PublicityPaper'"
            if SCENARIO_ENVIRONMENT == 'production':
                query += " AND r.isDefaultForProduction=true"
            elif SCENARIO_ENVIRONMENT == 'sandbox':
                query += " AND r.isDefaultForSandbox=true"
            if publicity_paper_keyword:
                query += f" AND r.publicityPaperKeyword='{publicity_paper_keyword}'"
            response = list(cosmosdb_scenario_data.query_items(query))
            if len(response) > 0\
            and response[0].get('dataId'):
                main_message_data_id = response[0]['dataId']
                self.main_message_data_id = main_message_data_id
                message = self.__generate_flex_message_helper__(response[0]['params'], response[0]['nameLBD'], 'PublicityPaper')
                return message
            else:
                return None

        except exceptions.CosmosHttpResponseError:
            # No data found
            return None

    # 混雑状況用関数
    def __getCongestionSituationSelectScenarioData__(self, message: str):
        try:
            if message.endswith("の混雑状況"):
                facility_name = message[:-5]
                cosmosdb_congestion_situation_data = cosmos_client.get_container_scenario(TABLE_CONGESTION_SITUATION, '/id')
                congestion_situation_query = f'SELECT * FROM r WHERE r.facilityName="{facility_name}"'
                congestion_situation_responce = list(cosmosdb_congestion_situation_data.query_items(
                    query=congestion_situation_query,
                    enable_cross_partition_query=True
                ))
                if len(congestion_situation_responce) == 0\
                or not congestion_situation_responce[0].get('space'):
                    return None
                facility = congestion_situation_responce[0]['space']
                custom = congestion_situation_responce[0].get('selectMessage')
                if SCENARIO_ENVIRONMENT == 'production' and custom and custom.get("disabled") == True:
                    return None
                scenario_data_item = self.__getScenarioData__(self.scenario, 'CONGESTION_SITUATION_SELECT_BUBBLE_TEMPLATE')
                if len(scenario_data_item) > 0:
                    return flex_message.generate_bubble(
                        self.__generate_cosmosdb_congestion_select_message__(scenario_data_item[0], facility_name, facility, custom)
                    )
                else:
                    return None
            else:
                return None
        except:
            return None

    def __getCongestionSituationScenarioData__(self, postback_data):
        cosmosdb_congestion_situation_data = cosmos_client.get_container_scenario(TABLE_CONGESTION_SITUATION, '/id')
        try:
            postback_data_json = json.loads(postback_data)
            if not postback_data_json:
                return None
            facility_name = postback_data_json.get('facilityName')
            if not facility_name:
                return None
            congestion_situation_query = f'SELECT * FROM r WHERE r.facilityName="{facility_name}"'
            congestion_situation_responce = list(cosmosdb_congestion_situation_data.query_items(
                query=congestion_situation_query,
                enable_cross_partition_query=True
            ))
            if len(congestion_situation_responce) == 0\
            or not congestion_situation_responce[0].get('space'):
                return None
            facility = congestion_situation_responce[0]
            scenario_data_item = self.__getScenarioData__(self.scenario, 'CONGESTION_SITUATION_BUBBLE_TEMPLATE')
            if not len(scenario_data_item) >= 1:
                return None
            spaces = facility['space']

            space_name = postback_data_json.get('spaceName')
            space_names = postback_data_json.get('spaceNames')
            if space_name:
                space = Enumerable(list(filter(lambda x: x.get('spaceName') == space_name, spaces))).first_or_default()
                if space and not space.get('disabled'):
                    message = flex_message.generate_bubble(
                        self.__generate_cosmosdb_congestion_message__(scenario_data_item[0], facility, space),
                        '混雑状況'
                    )
                    return message
                else:
                    message = None
                    scenario_data_item = self.__getScenarioData__(self.scenario, 'CONGESTION_SITUATION_NONE_TEXT')
                    if scenario_data_item:
                        message = self.__generateMessage__(scenario_data_item)
                    return message
            elif space_names:
                carousel_message = []
                spaces = Enumerable(list(filter(lambda x: x.get('spaceName') in space_names, spaces)))
                for space in spaces:
                    if not space.get('disabled'):
                        carousel_message.append({
                            "params":
                            self.__generate_cosmosdb_congestion_message__(scenario_data_item[0], facility, space),
                        })
                if len(carousel_message) > 0:
                    return flex_message.generate_carousel(
                        carousel_message,
                        '混雑状況'
                    )
                else:
                    message = None
                    scenario_data_item = self.__getScenarioData__(self.scenario, 'CONGESTION_SITUATION_NONE_TEXT')
                    if scenario_data_item:
                        message = self.__generateMessage__(scenario_data_item)
                    return message
            else:
                carousel_message = []
                for space in spaces:
                    if not space.get('disabled'):
                        carousel_message.append({
                            "params":
                            self.__generate_cosmosdb_congestion_message__(scenario_data_item[0], facility, space),
                        })
                if len(carousel_message) > 0:
                    return flex_message.generate_carousel(
                        carousel_message,
                        '混雑状況'
                    )
                else:
                    message = None
                    scenario_data_item = self.__getScenarioData__(self.scenario, 'CONGESTION_SITUATION_NONE_TEXT')
                    if scenario_data_item:
                        message = self.__generateMessage__(scenario_data_item)
                    return message

        except:
            message = None
            scenario_data_item = self.__getScenarioData__(self.scenario, 'CONGESTION_SITUATION_NONE_TEXT')
            if scenario_data_item:
                message = self.__generateMessage__(scenario_data_item)
            return message

    def __chat_mode_start__(self, event):
        try:
            postback_data_json = json.loads(event.postback.data)
            if not postback_data_json:
                return None
            cosmosdb_chat_list = cosmos_client.get_container_scenario(TABLE_CHATBOT_CHAT_LIST, '/id')
            query = f'SELECT * FROM c WHERE c.userId="{event.source.user_id}" AND NOT IsDefined(c.toDate)'
            unsolved_talk = list(cosmosdb_chat_list.query_items(
                query=query,
                enable_cross_partition_query=True
            ))
            if len(unsolved_talk) > 0:
                return self.message_generator["text"]({
                    "text": "既に相談を開始済みです。",
                    "specialScenarioTalk": "相談"
                })

            item = {
                "id": str(uuid.uuid4()),
                "userId": event.source.user_id,
                "name": postback_data_json.get('name'),
                "fromDate": int(str(event.timestamp)[0:10])
            }
            cosmosdb_chat_list.upsert_item(body=item)
            return self.message_generator["text"]({
                "text": "相談を開始します。相談員がお伺いしますのでしばらくお待ちください。",
                "specialScenarioTalk": "相談"
            })

        except:
            return None

    @staticmethod
    def __generate_cosmosdb_congestion_select_message__(template_message, facilityName, facilities, custom=None):
        try:
            message_json = template_message.get('params')
            if custom and custom.get('custom', False):
                message_json = custom.get('param')

            if (custom and custom.get('type', None) != 'json' and not custom.get('isCustomButton')) or custom is None:
                json_body = message_json.get('body', {}).get('contents')
                if (len(json_body) > 0 and json_body[0]['type'] == 'button'):
                    for facility in facilities:
                        if not facility.get('disabled'):
                            template_button = copy.deepcopy(json_body[0])
                            space_name = facility['spaceName']
                            if space_name:
                                template_button['action']['label'] = space_name
                                template_button['action']['displayText'] = space_name
                                template_button['action']['data'] = f'{{"facilityName": "{facilityName}", "spaceName": "{space_name}", "id": "CONGESTION_SITUATION_SELECT"}}'
                            json_body.append(template_button)

            scenario_data_str = json.dumps(
                message_json,
                ensure_ascii=False
            )
            scenario_data_str = scenario_data_str.replace(
                '${facilityName}',
                facilityName
            )
            scenario_data = json.loads(scenario_data_str)

            return scenario_data
        except:
            return None

    @staticmethod
    def __generate_cosmosdb_congestion_message__(template_message, facility, space):
        try:
            scenario_data_str = json.dumps(
                template_message.get('params'),
                ensure_ascii=False
            )
            scenario_data_str = scenario_data_str.replace(
                '${facilityName}',
                str(facility.get('facilityName'))
            )
            scenario_data_str = scenario_data_str.replace(
                '${spaceName}',
                str(space.get('spaceName'))
            )
            status = "不明"
            color = "#000000"
            if space.get('status') == 0:
                status = "営業時間外"
                color = "#9E9E9E"
            elif space.get('status') == 1:
                status = "空き"
                color = "#07B53B"
            elif space.get('status') == 2:
                status = "やや混雑"
                color = "#FF9800"
            elif space.get('status') == 3:
                status = "混雑"
                color = "#F44336"
            elif space.get('status').get('name') and space.get('status').get('color'):
                status = space.get('status').get('name')
                color = space.get('status').get('color')
            scenario_data_str = scenario_data_str.replace(
                '${status}',
                status
            )
            scenario_data_str = scenario_data_str.replace(
                '${color}',
                color
            )
            japanTimezone = datetime.timezone(datetime.timedelta(hours=9))
            last_update_timestamp = space.get('lastUpdateTime')
            last_update_time = str(datetime.datetime.fromtimestamp(
                last_update_timestamp,
                japanTimezone
            ))[0:-9]
            scenario_data_str = scenario_data_str.replace(
                '${lastUpdateTime}',
                last_update_time
            )
            memo = " "
            if space.get('memo'):
                memo = str(space.get('memo'))
            scenario_data_str = scenario_data_str.replace(
                '${memo}',
                memo
            )

            scenario_data = json.loads(scenario_data_str)

            image = space.get('image')
            if image:
                scenario_data['hero'] = {
                    "type": "image",
                    "url": f"{image}",
                    "size": "full",
                    "aspectRatio": "16:9",
                    "aspectMode": "cover"
                }

            return scenario_data
        except:
            return None
