import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import llm_service


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

        with (
            mock.patch.object(llm_service.request, "urlopen", side_effect=llm_service.error.URLError("refused")),
            self.assertRaises(llm_service.LLMUnavailableError),
        ):
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


class EnsureServerRunningTest(unittest.TestCase):
    """Caso real: o PC reiniciou, o Ollama nao subiu, a traducao pro chines
    falhou na transcricao e ninguem percebeu. O app agora liga o servidor."""

    def _client(self):
        return llm_service.OllamaClient(model="qwen-test", base_url="http://127.0.0.1:11434")

    def test_does_nothing_when_server_is_up(self):
        client = self._client()
        with mock.patch.object(client, "is_server_up", return_value=True), \
                mock.patch.object(llm_service.subprocess, "Popen") as popen:
            self.assertTrue(client.ensure_server_running())
        popen.assert_not_called()

    def test_starts_ollama_serve_and_waits_until_it_answers(self):
        client = self._client()
        with mock.patch.object(client, "is_server_up", side_effect=[False, False, True]), \
                mock.patch.object(llm_service, "resolve_ollama_executable", return_value="D:/Ollama/ollama.exe"), \
                mock.patch.object(llm_service.subprocess, "Popen") as popen, \
                mock.patch.object(llm_service.time, "sleep"):
            self.assertTrue(client.ensure_server_running())

        args = popen.call_args.args[0]
        self.assertEqual(args, ["D:/Ollama/ollama.exe", "serve"])

    def test_forwards_ollama_models_dir_to_the_server(self):
        client = self._client()
        with mock.patch.object(client, "is_server_up", side_effect=[False, True]), \
                mock.patch.object(llm_service, "resolve_ollama_executable", return_value="ollama"), \
                mock.patch.object(llm_service, "resolve_models_dir", return_value="D:/modelos"), \
                mock.patch.object(llm_service.subprocess, "Popen") as popen, \
                mock.patch.object(llm_service.time, "sleep"):
            client.ensure_server_running()

        self.assertEqual(popen.call_args.kwargs["env"]["OLLAMA_MODELS"], "D:/modelos")

    def test_returns_false_when_executable_is_not_found(self):
        client = self._client()
        with mock.patch.object(client, "is_server_up", return_value=False), \
                mock.patch.object(llm_service, "resolve_ollama_executable", return_value=None), \
                mock.patch.object(llm_service.subprocess, "Popen") as popen:
            self.assertFalse(client.ensure_server_running())
        popen.assert_not_called()

    def test_returns_false_when_server_never_answers(self):
        client = self._client()
        with mock.patch.object(client, "is_server_up", return_value=False), \
                mock.patch.object(llm_service, "resolve_ollama_executable", return_value="ollama"), \
                mock.patch.object(llm_service.subprocess, "Popen"), \
                mock.patch.object(llm_service.time, "sleep"):
            self.assertFalse(client.ensure_server_running(wait_seconds=3))

    def test_never_starts_a_server_for_a_remote_url(self):
        client = llm_service.OllamaClient(model="qwen-test", base_url="http://outra-maquina:11434")
        with mock.patch.object(client, "is_server_up", return_value=False), \
                mock.patch.object(llm_service.subprocess, "Popen") as popen:
            self.assertFalse(client.ensure_server_running())
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
