from panolog.classifier import Category
from panolog.storage import Repository, connect
from panolog.storage.repository import text_hash


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def make():
    clock = Clock()
    return Repository(connect(":memory:"), clock=clock), clock


def add(repo, text, **kw):
    return repo.add_item(Category.TEXT, text_hash(text), text=text, **kw)[0]


def test_sensitive_fields_roundtrip():
    repo, _ = make()
    item = add(repo, "TC 10000000146", sensitive=True, masked_text="TC *********46")
    assert item.sensitive and item.masked_text == "TC *********46"
    assert not add(repo, "normal").sensitive


def test_masked_item_is_not_searchable_by_hidden_part():
    repo, _ = make()
    add(repo, "TC 10000000146", sensitive=True, masked_text="TC *********46")
    assert repo.list_items(Category.TEXT, "100000001") == []
    assert len(repo.list_items(Category.TEXT, "TC")) == 1
    assert len(repo.list_items(Category.TEXT, "46")) == 1


def test_auto_delete_after_ttl():
    repo, clock = make()
    add(repo, "gizli", sensitive=True, expires_at=clock.t + 60)
    clock.t += 59
    assert repo.purge_expired() == 0
    clock.t += 1
    assert repo.purge_expired() == 1
    assert repo.count() == 0


def test_recopy_restarts_countdown():
    repo, clock = make()
    add(repo, "gizli", sensitive=True, expires_at=clock.t + 60)
    clock.t += 50
    again = add(repo, "gizli", sensitive=True, expires_at=clock.t + 60)
    assert again.expires_at == clock.t + 60
    clock.t += 30
    assert repo.purge_expired() == 0
    assert repo.count() == 1


def test_pinning_cancels_auto_delete():
    repo, clock = make()
    item = add(repo, "gizli", sensitive=True, expires_at=clock.t + 60)
    repo.set_pinned(item.id, True)
    assert repo.get(item.id).expires_at is None
    clock.t += 3600
    assert repo.purge_expired() == 0
    # sabitlenmiş öğe yeniden kopyalanınca süre geri gelmez
    assert add(repo, "gizli", sensitive=True, expires_at=clock.t + 60).expires_at is None
    # sabitleme kaldırılınca da kendiliğinden süreli olmaz
    repo.set_pinned(item.id, False)
    assert repo.get(item.id).expires_at is None


def test_recopy_refreshes_sensitive_state():
    repo, _ = make()
    add(repo, "TC 10000000146")
    item = add(repo, "TC 10000000146", sensitive=True, masked_text="TC *********46")
    assert item.sensitive and item.masked_text == "TC *********46"
    assert repo.count() == 1
