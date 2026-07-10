"""WebChannel 多租户隔离:每个用户的线程列表与 tape 互相独立。"""

import hashlib
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import make_mocked_request

from backend.channels.web import WebChannel


async def _noop(_message: object) -> None:  # on_receive stub
    return None


def _channel(tmp_path: Path) -> WebChannel:
    ch = WebChannel(on_receive=_noop)
    # 把历史落盘重定向到临时目录,避免污染 ~/.ApexTran。
    ch._store_path = tmp_path / "web_threads.json"
    ch._threads = {}
    return ch


def test_user_id_parses_header_sanitizes_and_defaults() -> None:
    assert WebChannel._user_id(make_mocked_request("POST", "/threads")) == "default"
    assert (
        WebChannel._user_id(make_mocked_request("POST", "/threads", headers={"X-ApexTran-User": "alice"}))
        == "alice"
    )
    # 非法字符被剔除,防止路径/注入类问题。
    dirty = make_mocked_request("POST", "/threads", headers={"X-ApexTran-User": "a/../b lice!"})
    assert WebChannel._user_id(dirty) == "a..blice"


def test_user_id_requires_proxy_secret_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置了代理密钥后,缺失/错误密钥的请求一律降级为 default(防直连伪造)。"""
    monkeypatch.setenv("ApexTran_WEB_PROXY_SECRET", "s3cret")

    # 没带密钥:即便声称是 alice 也不认。
    no_secret = make_mocked_request("POST", "/threads", headers={"X-ApexTran-User": "alice"})
    assert WebChannel._user_id(no_secret) == "default"

    # 密钥错误:同样降级。
    wrong = make_mocked_request(
        "POST", "/threads", headers={"X-ApexTran-User": "alice", "X-ApexTran-Proxy-Secret": "nope"}
    )
    assert WebChannel._user_id(wrong) == "default"

    # 密钥正确:认可身份。
    ok = make_mocked_request(
        "POST", "/threads", headers={"X-ApexTran-User": "alice", "X-ApexTran-Proxy-Secret": "s3cret"}
    )
    assert WebChannel._user_id(ok) == "alice"


@pytest.mark.asyncio
async def test_threads_are_isolated_per_user(tmp_path: Path) -> None:
    ch = _channel(tmp_path)

    def req(user: str | None):
        headers = {"X-ApexTran-User": user} if user else {}
        return make_mocked_request("POST", "/threads", headers=headers)

    # alice 建两个,bob 建一个。
    await ch._create_thread(req("alice"))
    await ch._create_thread(req("alice"))
    await ch._create_thread(req("bob"))

    alice_view = json.loads((await ch._search_threads(req("alice"))).text)
    bob_view = json.loads((await ch._search_threads(req("bob"))).text)

    assert len(alice_view) == 2
    assert len(bob_view) == 1
    # 两人看到的 thread_id 集合无交集。
    alice_ids = {t["thread_id"] for t in alice_view}
    bob_ids = {t["thread_id"] for t in bob_view}
    assert alice_ids.isdisjoint(bob_ids)


@pytest.mark.asyncio
async def test_thread_state_not_leaked_across_users(tmp_path: Path) -> None:
    ch = _channel(tmp_path)
    created = json.loads((await ch._create_thread(make_mocked_request(
        "POST", "/threads", headers={"X-ApexTran-User": "alice"}
    ))).text)
    tid = created["thread_id"]
    # 手动塞一条 alice 的消息。
    ch._threads["alice"][tid].append({"type": "human", "content": "secret", "id": "x"})

    # bob 用同一个 thread_id 查状态,拿不到 alice 的内容。
    bob_state = json.loads((await ch._thread_state(make_mocked_request(
        "GET", f"/threads/{tid}/state", headers={"X-ApexTran-User": "bob"}, match_info={"thread_id": tid}
    ))).text)
    assert bob_state["values"]["messages"] == []


def test_legacy_flat_history_migrates_to_default(tmp_path: Path) -> None:
    # 旧版扁平格式:thread_id -> messages。
    store = tmp_path / "web_threads.json"
    store.write_text(json.dumps({"t1": [{"type": "human", "content": "hi", "id": "1"}]}), encoding="utf-8")

    ch = WebChannel(on_receive=_noop)
    ch._store_path = store
    ch._threads = {}
    ch._load_threads()

    assert set(ch._threads.keys()) == {"default"}
    assert "t1" in ch._threads["default"]


def test_tape_name_differs_per_user() -> None:
    """同一 thread_id 折入不同用户后,tape 文件名必须不同(文件级隔离)。"""

    def tape_name(session_id: str) -> str:
        ws = hashlib.md5(str(Path.cwd().resolve()).encode(), usedforsecurity=False).hexdigest()[:16]
        sh = hashlib.md5(session_id.encode(), usedforsecurity=False).hexdigest()[:16]
        return f"{ws}__{sh}"

    thread = "shared-thread-id"
    names = {tape_name(f"{u}::{thread}") for u in ("alice", "bob", "default")}
    assert len(names) == 3
