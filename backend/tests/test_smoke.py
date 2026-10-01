import warehouse_ops


def test_package_imports() -> None:
    assert warehouse_ops.__doc__ is not None
