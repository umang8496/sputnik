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
incident  mode            chars      tokens chars/tok  verdict
INC-001   filtered        2,154       1,399       1.5  ok to send
INC-001   raw           288,656     146,105       2.0  ok to send
INC-101   filtered       10,493       6,911       1.5  ok to send
INC-101   raw         4,875,033   2,447,231       2.0  does not fit window
A first call                 write=  2318  read=     0  input=   12  total=  2330
B same request, +5s          write=     0  read=  2318  input=   12  total=  2330
C SYSTEM + one space         write=     0  read=  2318  input=   12  total=  2330
```
