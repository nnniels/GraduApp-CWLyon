from graduapp import create_app


def test_index_loads():
    print("...test")
    client = create_app({"TESTING": True}).test_client()
    print("...testy crousty")
    print( client.get("/").status_code)
    assert client.get("/").status_code == 200
