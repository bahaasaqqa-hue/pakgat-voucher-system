from __future__ import annotations


OLD_FALLBACK = (
    '                    generated_reply = "أعتذر عن الرد السابق. معك جود من باكيجات بخصوص فرصة الشراكة؛ '
    'أرسل لي اسم النشاط والمدينة ونوع الخدمات لأوضح لكم الخطوة المناسبة."'
)

NEW_FALLBACK = (
    '                    generated_reply = "أكيد 👌 إذا تقصد كيف تتم آلية التعاون مع بكجات: نجهز معكم العرض، '
    'نبرزه ونسوّق له، والعميل يشتري القسيمة الرقمية من بكجات ويستبدلها عندكم بسهولة. '
    'وإذا كنت تقصد شيئًا آخر، اكتب لي النقطة اللي تقصدها وأنا أوضحها مباشرة."'
)


def patch_source_text(source: str) -> str:
    """Replace only the known merchant outbound fallback, failing closed otherwise."""
    if NEW_FALLBACK in source:
        raise ValueError("merchant follow-up fallback is already patched")
    count = source.count(OLD_FALLBACK)
    if count != 1:
        raise ValueError(f"expected exactly one merchant fallback, found {count}")
    return source.replace(OLD_FALLBACK, NEW_FALLBACK, 1)


def patch_file(path: str) -> None:
    from pathlib import Path

    target = Path(path)
    source = target.read_text(encoding="utf-8")
    patched = patch_source_text(source)
    target.write_text(patched, encoding="utf-8")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    patch_file(args.path)
