<!-- markdownlint-disable MD001 -->
<!-- markdownlint-disable MD024 -->
<!-- markdownlint-disable MD025 -->
<!-- markdownlint-disable MD026 -->
<!-- markdownlint-disable MD029 -->
<!-- markdownlint-disable MD033 -->
<!-- markdownlint-disable MD040 -->
<!-- markdownlint-disable MD056 -->
<!-- markdownlint-disable MD060 -->

# Result

```code
client config: timeout=Timeout(connect=5.0, read=600, write=600, pool=600)  max_retries=2
AuthenticationError status=401
elapsed 0.3s -> exit code 2
```

```code
client config: timeout=60.0  max_retries=4
AuthenticationError status=401
elapsed 0.4s -> exit code 2
```

```code
client config: timeout=60.0  max_retries=4
OverloadedError status=529
elapsed 6.6s -> exit code 3
```
