from graduapp import create_app


def test_index_loads():
    client = create_app({"TESTING": True}).test_client()
    assert client.get("/").status_code == 200
