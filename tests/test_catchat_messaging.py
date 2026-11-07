import tempfile
import unittest

from catchat_server import create_app


class CatChatMessagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.agent_calls = []
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.temp.name + "/catchat.sqlite3",
                "SSE_SECONDS": 1,
            },
            ai_responder=lambda message, session_id: (
                self.agent_calls.append((message, session_id)) or "AI reply: " + message
            ),
        )
        self.client = self.app.test_client()
        self.alice = self._register_and_login("alice")
        self.bob = self._register_and_login("bob")
        self.charlie = self._register_and_login("charlie")

    def tearDown(self):
        self.temp.cleanup()

    def _register_and_login(self, username):
        created = self.client.post("/v1/accounts", json={
            "username": username,
            "display_name": username.title(),
            "password": "correct horse battery staple",
        })
        self.assertEqual(created.status_code, 201)
        logged_in = self.client.post("/v1/sessions", json={
            "username": username,
            "password": "correct horse battery staple",
        })
        self.assertEqual(logged_in.status_code, 200)
        return {"Authorization": "Bearer " + logged_in.json["token"]}

    def test_direct_messages_are_visible_only_to_participants(self):
        created = self.client.post(
            "/v1/conversations/direct",
            headers=self.alice,
            json={"recipient_username": "bob"},
        )
        self.assertEqual(created.status_code, 200)
        conversation_id = created.json["conversation_id"]

        sent = self.client.post(
            f"/v1/conversations/{conversation_id}/messages",
            headers=self.alice,
            json={"content": "A private message"},
        )
        self.assertEqual(sent.status_code, 201)
        messages = self.client.get(
            f"/v1/conversations/{conversation_id}/messages",
            headers=self.bob,
        )
        self.assertEqual(messages.status_code, 200)
        self.assertEqual(messages.json["messages"][0]["content"], "A private message")

        denied = self.client.get(
            f"/v1/conversations/{conversation_id}/messages",
            headers=self.charlie,
        )
        self.assertEqual(denied.status_code, 403)

    def test_group_messages_and_membership(self):
        created = self.client.post(
            "/v1/conversations/group",
            headers=self.alice,
            json={"name": "Project room", "participants": ["bob", "charlie", "BOB"]},
        )
        self.assertEqual(created.status_code, 201)
        conversation_id = created.json["conversation_id"]
        sent = self.client.post(
            f"/v1/conversations/{conversation_id}/messages",
            headers=self.bob,
            json={"content": "Group update"},
        )
        self.assertEqual(sent.status_code, 201)
        received = self.client.get(
            f"/v1/conversations/{conversation_id}/messages",
            headers=self.charlie,
        )
        self.assertEqual(received.json["messages"][0]["content"], "Group update")

    def test_agent_direct_message_uses_conversation_scoped_session(self):
        created = self.client.post(
            "/v1/conversations/direct",
            headers=self.alice,
            json={"recipient_username": "astrologically-intelligent"},
        )
        self.assertEqual(created.status_code, 200)
        conversation_id = created.json["conversation_id"]
        sent = self.client.post(
            f"/v1/conversations/{conversation_id}/messages",
            headers=self.alice,
            json={"content": "Research this subject"},
        )
        self.assertEqual(sent.status_code, 201)
        messages = sent.json["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[1]["sender"], "astrologically-intelligent")
        self.assertEqual(messages[1]["content"], "AI reply: Research this subject")
        self.assertEqual(self.agent_calls, [("Research this subject", "catchat_" + conversation_id)])
        self.assertEqual(messages[1]["reply_to_message_id"], messages[0]["id"])

    def test_unconfigured_agent_leaves_the_human_message_stored(self):
        created = self.client.post(
            "/v1/conversations/direct",
            headers=self.alice,
            json={"recipient_username": "astrologically-intelligent"},
        )
        conversation_id = created.json["conversation_id"]
        sent = self.client.post(
            f"/v1/conversations/{conversation_id}/messages",
            headers=self.alice,
            json={"content": "Please respond"},
        )
        self.assertEqual(sent.status_code, 502)
        history = self.client.get(
            f"/v1/conversations/{conversation_id}/messages",
            headers=self.alice,
        )
        self.assertEqual(len(history.json["messages"]), 1)
        self.assertEqual(history.json["messages"][0]["content"], "Please respond")

    def test_read_receipts_update_for_members(self):
        created = self.client.post(
            "/v1/conversations/direct",
            headers=self.alice,
            json={"recipient_username": "bob"},
        )
        conversation_id = created.json["conversation_id"]
        sent = self.client.post(
            f"/v1/conversations/{conversation_id}/messages",
            headers=self.alice,
            json={"content": "Read this"},
        )
        message_id = sent.json["messages"][0]["id"]
        marked = self.client.post(
            f"/v1/conversations/{conversation_id}/read",
            headers=self.bob,
            json={"message_id": message_id},
        )
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(marked.json["last_read_message_id"], message_id)

    def test_invalid_messages_and_missing_auth_are_rejected(self):
        no_auth = self.client.get("/v1/conversations")
        self.assertEqual(no_auth.status_code, 401)
        invalid = self.client.post(
            "/v1/conversations/direct",
            headers=self.alice,
            json={"recipient_username": "missing"},
        )
        self.assertEqual(invalid.status_code, 404)
        bad_message = self.client.post(
            "/v1/conversations/direct",
            headers=self.alice,
            json={"recipient_username": "bob"},
        )
        conversation_id = bad_message.json["conversation_id"]
        rejected = self.client.post(
            f"/v1/conversations/{conversation_id}/messages",
            headers=self.alice,
            json={"content": " "},
        )
        self.assertEqual(rejected.status_code, 400)


if __name__ == "__main__":
    unittest.main()
