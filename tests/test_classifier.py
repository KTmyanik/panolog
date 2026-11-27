import pytest

from panolog.classifier import Category, classify, classify_text, is_url


@pytest.mark.parametrize(
    "text",
    [
        "https://example.com",
        "http://example.com/path?q=1#frag",
        "HTTPS://EXAMPLE.COM",
        "  https://example.com/a  \n",
        "www.example.com",
        "example.com",
        "sub.domain.com.tr/yol",
        "github.com/user/repo",
        "example.com:8080/x",
        "http://localhost.local/x",
        "https://tr.wikipedia.org/wiki/İstanbul",
    ],
)
def test_urls(text):
    assert is_url(text)
    assert classify_text(text) is Category.LINK


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "merhaba dünya",
        "https://example.com adresine bak",
        "bak: https://example.com",
        "https://a.com\nhttps://b.com",
        "rapor.txt",
        "main.py",
        "ornek.docx",
        "ali@example.com",
        "1.5",
        "v1.2.3",
        "http://",
        "Sayın.Yetkili",
    ],
)
def test_non_urls(text):
    assert not is_url(text)


def test_link_does_not_fall_into_text():
    assert classify(has_files=False, has_image=False, text="https://example.com") is Category.LINK


def test_priority_files_then_text_then_image():
    assert classify(has_files=True, has_image=True, text="x") is Category.FILE
    # Excel hücresi gibi: metin + görsel birlikte gelirse metin sayılır
    assert classify(has_files=False, has_image=True, text="hücre") is Category.TEXT
    assert classify(has_files=False, has_image=True, text=None) is Category.IMAGE
    assert classify(has_files=False, has_image=True, text="  \n") is Category.IMAGE


def test_empty_clipboard():
    assert classify(has_files=False, has_image=False, text=None) is None
    assert classify(has_files=False, has_image=False, text="") is None
