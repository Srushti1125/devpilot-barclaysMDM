def test_auth_rate_limit_returns_retry_after_header(client):
    responses = [
        client.post(
            "/api/v1/auth/login",
            json={"email": "missing@example.com", "password": "invalid"},
        )
        for _ in range(11)
    ]

    assert all(response.status_code == 401 for response in responses[:10])
    limited = responses[-1]
    assert limited.status_code == 429
    assert limited.json() == {"detail": "Rate limit exceeded"}
    assert int(limited.headers["Retry-After"]) > 0
