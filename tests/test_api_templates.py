"""模板块写接口测试。

设计文档 §6.3 定了「模板块不能随手删，须进模板编辑页」——但这条规则
此前只写在文档里，接口和界面都没实现，也从未被测试覆盖。本文件把
接口契约钉住：

1. 增删改必须能真正改变库内容（否则配置化只是换了个地方看不到动静）。
2. 与 POST 同一套校验必须同样作用于 PUT——只校验创建不校验修改，
   等于把校验漏了一半（改一次就能绕过）。
3. 删除不存在的块必须 404。返回 200 会让前端误以为删成功了。
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setenv("APP_PASSWORD", "testpw")
    import app.auth as auth
    auth._sessions.clear()
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(client):
    assert client.post("/api/login", json={"password": "testpw"}).status_code == 200
    return client


@pytest.fixture
def tid(auth_client):
    return auth_client.get("/api/templates").json()[0]["id"]


def _first_block(auth_client, tid):
    return auth_client.get(f"/api/templates/{tid}/blocks").json()[0]


# ---------- POST ----------

def test_add_block_actually_persists(auth_client, tid):
    before = len(auth_client.get(f"/api/templates/{tid}/blocks").json())
    r = auth_client.post(f"/api/templates/{tid}/blocks",
                         json={"start_min": 100, "end_min": 130,
                               "name": "晨间复盘", "category": "项目推进"})
    assert r.status_code == 200
    after = auth_client.get(f"/api/templates/{tid}/blocks").json()
    assert len(after) == before + 1
    added = [b for b in after if b["name"] == "晨间复盘"]
    assert len(added) == 1
    assert (added[0]["start_min"], added[0]["end_min"]) == (100, 130)


def test_add_block_appends_to_end(auth_client, tid):
    """新增块应排在末尾，否则 sort_order 会与既有块冲突。"""
    auth_client.post(f"/api/templates/{tid}/blocks",
                     json={"start_min": 100, "end_min": 130, "name": "末位"})
    blocks = auth_client.get(f"/api/templates/{tid}/blocks").json()
    assert blocks[-1]["name"] == "末位"


def test_add_block_requires_name(auth_client, tid):
    r = auth_client.post(f"/api/templates/{tid}/blocks",
                         json={"start_min": 100, "end_min": 130, "name": "  "})
    assert r.status_code == 422


def test_add_block_requires_start_and_end(auth_client, tid):
    assert auth_client.post(f"/api/templates/{tid}/blocks",
                            json={"name": "缺时间"}).status_code == 422


def test_add_block_to_missing_template_404(auth_client):
    r = auth_client.post("/api/templates/99999/blocks",
                         json={"start_min": 100, "end_min": 130, "name": "x"})
    assert r.status_code == 404


def test_add_block_rejects_end_before_start(auth_client, tid):
    """结束早于开始是敲错，不是跨零点意图——模板编辑是刻意操作，不该猜。"""
    r = auth_client.post(f"/api/templates/{tid}/blocks",
                         json={"start_min": 600, "end_min": 300, "name": "反向"})
    assert r.status_code == 422


def test_add_block_rejects_out_of_range(auth_client, tid):
    assert auth_client.post(f"/api/templates/{tid}/blocks",
                            json={"start_min": -10, "end_min": 30,
                                  "name": "负值"}).status_code == 422
    assert auth_client.post(f"/api/templates/{tid}/blocks",
                            json={"start_min": 100, "end_min": 2000,
                                  "name": "超界"}).status_code == 422


# ---------- PUT ----------

def test_update_block_name_persists(auth_client, tid):
    b = _first_block(auth_client, tid)
    r = auth_client.put(f"/api/template-blocks/{b['id']}", json={"name": "改名后"})
    assert r.status_code == 200
    got = [x for x in auth_client.get(f"/api/templates/{tid}/blocks").json()
           if x["id"] == b["id"]][0]
    assert got["name"] == "改名后"


def test_update_block_times_persist(auth_client, tid):
    b = _first_block(auth_client, tid)
    auth_client.put(f"/api/template-blocks/{b['id']}",
                    json={"start_min": 391, "end_min": 421})
    got = [x for x in auth_client.get(f"/api/templates/{tid}/blocks").json()
           if x["id"] == b["id"]][0]
    assert (got["start_min"], got["end_min"]) == (391, 421)


def test_update_block_category_persists(auth_client, tid):
    b = _first_block(auth_client, tid)
    auth_client.put(f"/api/template-blocks/{b['id']}", json={"category": "睡眠"})
    got = [x for x in auth_client.get(f"/api/templates/{tid}/blocks").json()
           if x["id"] == b["id"]][0]
    assert got["category"] == "睡眠"


def test_update_rejects_empty_name(auth_client, tid):
    """PUT 必须与 POST 同规则：空名字会把块变成无名块，界面上无法辨认。"""
    b = _first_block(auth_client, tid)
    assert auth_client.put(f"/api/template-blocks/{b['id']}",
                           json={"name": "   "}).status_code == 422


def test_update_rejects_end_before_start(auth_client, tid):
    """只改 end 而不改 start 时同样要挡住反向区间。"""
    b = _first_block(auth_client, tid)
    assert auth_client.put(f"/api/template-blocks/{b['id']}",
                           json={"end_min": b["start_min"] - 5}).status_code == 422


def test_update_rejects_out_of_range(auth_client, tid):
    b = _first_block(auth_client, tid)
    assert auth_client.put(f"/api/template-blocks/{b['id']}",
                           json={"start_min": -1}).status_code == 422


def test_update_missing_block_404(auth_client):
    assert auth_client.put("/api/template-blocks/99999",
                           json={"name": "x"}).status_code == 404


def test_update_ignores_unknown_fields(auth_client, tid):
    """未在白名单里的字段应被忽略而非报错，也绝不能写进库。"""
    b = _first_block(auth_client, tid)
    r = auth_client.put(f"/api/template-blocks/{b['id']}",
                        json={"template_id": 999, "id": 12345})
    assert r.status_code == 200
    got = [x for x in auth_client.get(f"/api/templates/{tid}/blocks").json()
           if x["id"] == b["id"]][0]
    assert got["template_id"] == tid


# ---------- DELETE ----------

def test_delete_block_removes_it(auth_client, tid):
    blocks = auth_client.get(f"/api/templates/{tid}/blocks").json()
    victim = blocks[-1]
    assert auth_client.delete(
        f"/api/template-blocks/{victim['id']}").status_code == 200
    left = auth_client.get(f"/api/templates/{tid}/blocks").json()
    assert victim["id"] not in [x["id"] for x in left]
    assert len(left) == len(blocks) - 1


def test_delete_missing_block_404(auth_client):
    """返回 200 会让前端误以为删除成功，实际什么都没发生。"""
    assert auth_client.delete("/api/template-blocks/99999").status_code == 404


# ---------- 改动真的影响对照结果 ----------

def test_edited_template_changes_compare_result(auth_client, tid):
    """端到端：改模板必须改变对照判定，否则「可编辑」是假的。

    「早操」原本 390-420。把实际块记在 390-420 应判 aligned；
    把模板块整体挪到 600-630 后，同一实际块就不再命中。
    """
    auth_client.post("/api/actual/quick",
                     json={"date": "2026-09-20", "line": "06:35-07:02 早操"})
    rows = auth_client.get("/api/compare?date=2026-09-20").json()["rows"]
    before = [r for r in rows if r["template_name"] == "早操"][0]
    assert before["status"] == "aligned"

    block = [b for b in auth_client.get(f"/api/templates/{tid}/blocks").json()
             if b["name"] == "早操"][0]
    assert auth_client.put(f"/api/template-blocks/{block['id']}",
                           json={"start_min": 600, "end_min": 630}).status_code == 200

    rows = auth_client.get("/api/compare?date=2026-09-20").json()["rows"]
    after = [r for r in rows if r["template_name"] == "早操"][0]
    assert after["status"] == "unrecorded"


def test_template_blocks_are_not_soft_deleted(auth_client, tid):
    """模板块是硬删除。与 actual_blocks 的软删除语义不同，别混。

    actual_blocks 保留 deleted_at 是为了「上周三删错了」能追溯；
    模板块删掉就是基准线上少了一格，历史日报按新模板重算即可，
    不需要保留墓碑。
    """
    cols = set(auth_client.get(f"/api/templates/{tid}/blocks").json()[0].keys())
    assert "deleted_at" not in cols
