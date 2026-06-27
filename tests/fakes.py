from __future__ import annotations


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, name: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and name in self.values:
            return False
        self.values[name] = value
        return True

    def get(self, name: str):
        return self.values.get(name)

    def delete(self, *names: str):
        deleted = 0
        for name in names:
            if name in self.values:
                del self.values[name]
                deleted += 1
        return deleted

    def incr(self, name: str):
        value = int(self.values.get(name, "0")) + 1
        self.values[name] = str(value)
        return value

    def decr(self, name: str):
        value = int(self.values.get(name, "0")) - 1
        self.values[name] = str(value)
        return value

    def expire(self, name: str, time: int):
        return name in self.values

    def eval(self, script: str, numkeys: int, *keys_and_args):
        key = keys_and_args[0]
        expected_value = keys_and_args[numkeys]
        if self.values.get(key) == expected_value:
            del self.values[key]
            return 1
        return 0


class FailingRedis(FakeRedis):
    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        super().__init__()
        self.fail_on = fail_on or set()

    def _maybe_fail(self, operation: str) -> None:
        if operation in self.fail_on:
            from redis.exceptions import TimeoutError

            raise TimeoutError(f"{operation} timed out")

    def set(self, name: str, value: str, nx: bool = False, ex: int | None = None):
        self._maybe_fail("set")
        return super().set(name, value, nx=nx, ex=ex)

    def get(self, name: str):
        self._maybe_fail("get")
        return super().get(name)

    def delete(self, *names: str):
        self._maybe_fail("delete")
        return super().delete(*names)

    def incr(self, name: str):
        self._maybe_fail("incr")
        return super().incr(name)

    def decr(self, name: str):
        self._maybe_fail("decr")
        return super().decr(name)

    def expire(self, name: str, time: int):
        self._maybe_fail("expire")
        return super().expire(name, time)

    def eval(self, script: str, numkeys: int, *keys_and_args):
        self._maybe_fail("eval")
        return super().eval(script, numkeys, *keys_and_args)
