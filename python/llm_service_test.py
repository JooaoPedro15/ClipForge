import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import llm_service  # noqa: E402


def _fake_response(payload: dict) -> mock.MagicMock:
    body = json.dumps(payload).encode("utf-8")
    response = mock.MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    return response


class ParseJsonTest(unittest.TestCase):
    def test_parses_raw_json(self):
        self.assertEqual(llm_service.parse_json_payload('{"a": 1}'), {"a": 1})

    def test_strips_markdown_fence(self):
        text = '```json\n{"a": [1, 2]}\n```'
        self.assertEqual(llm_service.parse_json_payload(text), {"a": [1, 2]})

    def test_extracts_json_object_surrounded_by_commentary(self):
        text = 'Aqui esta:\n{"a": 1}\nEspero que ajude.'
        self.assertEqual(llm_service.parse_json_payload(text), {"a": 1})

    def test_raises_on_garbage(self):
        with self.assertRaises(llm_service.LLMResponseError):
            llm_service.parse_json_payload("nada de json aqui")


class OllamaClientTest(unittest.TestCase):
    def test_chat_json_sends_temperature_zero_and_json_format(self):
        client = llm_service.OllamaClient(model="qwen-test", base_url="http://host:1")
        response = _fake_response({"message": {"content": '{"ok": true}'}})

        with mock.patch.object(llm_service.request, "urlopen", return_value=response) as urlopen:
            result = client.chat_json(system="sys", user="usr")

        self.assertEqual(result, {"ok": True})
        req = urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "http://host:1/api/chat")
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["model"], "qwen-test")
        self.assertFalse(body["stream"])
        self.assertEqual(body["format"], "json")
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertEqual(body["messages"][0], {"role": "system", "content": "sys"})
        self.assertEqual(body["messages"][1], {"role": "user", "content": "usr"})

    def test_chat_json_raises_unavailable_when_server_down(self):
        client = llm_service.OllamaClient(model="qwen-test", base_url="http://host:1")

        with mock.patch.object(llm_service.request, "urlopen", side_effect=llm_service.error.URLError("refused")):
            with self.assertRaises(llm_service.LLMUnavailableError):
                client.chat_json(system="sys", user="usr")

    def test_is_available_false_when_server_down(self):
        client = llm_service.OllamaClient(model="qwen-test", base_url="http://host:1")

        with mock.patch.object(llm_service.request, "urlopen", side_effect=llm_service.error.URLError("refused")):
            self.assertFalse(client.is_available())

    def test_is_available_false_when_model_not_pulled(self):
        client = llm_service.OllamaClient(model="qwen-test", base_url="http://host:1")
        response = _fake_response({"models": [{"name": "outro:latest"}]})

        with mock.patch.object(llm_service.request, "urlopen", return_value=response):
            self.assertFalse(client.is_available())

    def test_is_available_true_when_model_listed(self):
        client = llm_service.OllamaClient(model="qwen-test", base_url="http://host:1")
        response = _fake_response({"models": [{"name": "qwen-test"}]})

        with mock.patch.object(llm_service.request, "urlopen", return_value=response):
            self.assertTrue(client.is_available())

    def test_is_available_true_when_model_listed_with_latest_tag(self):
        client = llm_service.OllamaClient(model="qwen-test", base_url="http://host:1")
        response = _fake_response({"models": [{"name": "qwen-test:latest"}]})

        with mock.patch.object(llm_service.request, "urlopen", return_value=response):
            self.assertTrue(client.is_available())


class ResolveConfigTest(unittest.TestCase):
    def test_defaults_when_env_unset(self):
        with mock.patch.dict(llm_service.os.environ, {}, clear=True):
            client = llm_service.create_default_client()

        self.assertEqual(client.model, llm_service.DEFAULT_MODEL)
        self.assertEqual(client.base_url, llm_service.DEFAULT_BASE_URL)

    def test_env_overrides(self):
        env = {"CLIPFORGE_OLLAMA_URL": "http://x:9/", "CLIPFORGE_OLLAMA_MODEL": "m"}
        with mock.patch.dict(llm_service.os.environ, env, clear=True):
            client = llm_service.create_default_client()

        self.assertEqual(client.model, "m")
        # barra final removida pra nao gerar "//api/chat"
        self.assertEqual(client.base_url, "http://x:9")


if __name__ == "__main__":
    unittest.main()
