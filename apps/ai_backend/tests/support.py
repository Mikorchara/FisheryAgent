"""Independent fake SDK and responses. No Prototype fixtures or live transport."""
from types import SimpleNamespace as NS


class ScriptedGateway:
    def __init__(self, responses=()):
        self._responses = iter(responses)

    def complete(self, request, runtime):
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def delta(arguments=None, *, name=None, identifier=None, index=0):
    return NS(index=index, id=identifier, type="function" if identifier else None,
              function=NS(name=name, arguments=arguments))


def chunk(calls=None, *, content=None, finish=None, model="fixture-model", usage=None):
    return NS(id="fixture-response", model=model, usage=usage,
        choices=[NS(index=0, delta=NS(role="assistant", content=content,
            reasoning_content=None, tool_calls=calls), finish_reason=finish)])


USAGE = NS(prompt_tokens=2, completion_tokens=3, total_tokens=5)


def tool_chunks(name, identifier="call_1", arguments="{}"):
    midpoint = len(arguments) // 2
    return [chunk([delta(name=name[:5], identifier=identifier)]),
            chunk([delta(arguments[:midpoint], name=name[5:])]),
            chunk([delta(arguments[midpoint:])]), chunk(finish="tool_calls", usage=USAGE)]


def final_chunks(text="安全回答", finish="stop"):
    return [chunk(content=text[:2]), chunk(content=text[2:], finish=finish, usage=USAGE)]


class FakeSDK:
    """Same SDK boundary for Normal and Streaming, records cleanup before handlers."""
    def __init__(self, plans, *, model="fixture-model", on_close=None):
        self.plans, self.model, self.on_close = plans, model, on_close
        self.bodies, self.clients, self.lifecycle = [], [], []

    def factory(self, runtime, remaining):
        owner = self
        index = len(self.clients)

        class Stream:
            closed = False
            def __init__(self, items): self.items = items
            def __aiter__(self): return self.events()
            async def events(self):
                for item in self.items:
                    if isinstance(item, Exception): raise item
                    item.model = owner.model
                    yield item
            async def close(self):
                self.closed = True
                owner.lifecycle.append(("stream_closed", index))

        class Client:
            closed, stream = False, None
            def __init__(self): self.chat = NS(completions=NS(create=self.create))
            async def create(self, **body):
                owner.bodies.append(body)
                plan = owner.plans(index + 1, body) if callable(owner.plans) else owner.plans[index]
                if isinstance(plan, Exception): raise plan
                if body.get("stream"):
                    self.stream = Stream(plan)
                    return self.stream
                return plan
            async def close(self):
                self.closed = True
                owner.lifecycle.append(("client_closed", index))
                if owner.on_close: owner.on_close(index)

        client = Client()
        self.clients.append(client)
        return client


def sdk_final(text="安全回答", finish="stop", model="fixture-model"):
    return NS(model=model, usage=USAGE, choices=[NS(finish_reason=finish,
        message=NS(role="assistant", content=text, tool_calls=[], reasoning_content=None))])


def sdk_tool(name, identifier="call_1", arguments="{}", model="fixture-model"):
    return NS(model=model, usage=USAGE, choices=[NS(finish_reason="tool_calls",
        message=NS(role="assistant", content=None, reasoning_content=None,
            tool_calls=[NS(id=identifier, type="function", function=NS(name=name, arguments=arguments))]))])
