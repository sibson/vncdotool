# Pluggable Security Handlers

`specs/decoder-architecture.md` is the design this mirrors. Read that first;
this document only records where authentication differs from rectangle
decoding, and what the migration has to preserve.

## The handshake is a trampoline

Every security type in `rfb.py` is a chain of `expect(callback, n)` hops, each
method parking the next. Authentication is 20 of them:

| Security type | Methods |
|---|---|
| None | `_handleSecurityTypes` inline, version-dependent |
| VNC Authentication (2) | `_handleVNCAuth` |
| VeNCrypt (19) | `_handleVeNCryptVersion`, `…VersionAck`, `…SubtypeCount`, `…Subtypes`, `…TLSAck`, `_startVeNCryptSubAuth`, `_sendVeNCryptPlain` |
| ARD Diffie-Hellman (30) | `_handleDHAuth`, `_handleDHAuthKey`, `_handleDHAuthCert`, `_encryptArd` |
| shared tail | `_handleVNCAuthResult`, `_handleAuthFailed`, `_handleAuthFailedMessage` |

Two costs, and neither is line count:

**Handler-local state is stored on the client.** `self._challenge`,
`self.generator`, `self.keyLen`, `self.modulus`, `self.serverKey` exist only
because a callback cannot keep a local variable alive across a hop. They are
live on `RFBClient` for the whole session, long after the handshake that used
them, and nothing stops a later method reading a stale one.

**The shared tail is hardcoded at six call sites.** `expect(self._handleVNCAuthResult, 4)`
appears once per path that ends in a SecurityResult. Whether a SecurityResult
follows at all is a protocol rule — RFB 3.3 and 3.7 send none after security
type None — and that rule is currently spelled out wherever someone remembered
it.

## `_pump` already does this, at any phase

`RFBClient._pump` takes any generator, an `on_done`, and a description; it is
built on `expect` and knows nothing about rectangles. `messages/base.py`
already defines the contract it drives:

```python
def handle(self, client: Any) -> Generator[int, bytes, None]:
    """Yield the byte counts this message needs, each satisfied in full."""
```

Nothing binds that to the post-handshake loop. A security handler can be the
same generator, driven by the same pump, during the handshake. No new
machinery — this migration adds a package and a base class, not a mechanism.

## Reads are sequenced, writes are not

The generator suspends only on *reads*. Writes are ordinary side effects a
handler performs whenever it likes, including from code the handler does not
control.

This is what makes VNC authentication migratable without breaking its public
API. `rfb.py` documents `vncRequestPassword` as an override point that calls
`sendPassword` — the three in-tree implementations all call it synchronously,
but the docstring invites a subclass to call it later, out of band. The
handler must therefore **not** model the password as something it yields for.
It stashes the challenge, calls `client.vncRequestPassword()`, and goes
straight to waiting for the next read. Whenever `sendPassword` fires, it
writes; the generator neither knows nor cares.

**Do not change that contract in this migration.** `vncRequestPassword`,
`sendPassword`, `ardRequestCredentials` and `vncAuthFailed` keep their present
signatures and semantics. They are published, and `docs/library.rst` documents
subclassing.

## The contract

`vncdotool/security/base.py`:

```python
class SecurityHandler:
    """One RFB security type: RFC 6143 section 7.2."""

    SECURITY_TYPE: ClassVar[AuthTypes]

    def handle(self, client: Any) -> Generator[int, bytes, None]:
        """Yield the byte counts this security type needs, each satisfied in
        full. The security-type byte has already been written.
        """
        raise NotImplementedError
```

Registry mirrors `messages/__init__.py`: a `HANDLERS` dict keyed on
`AuthTypes`, and `for_connection()` returning fresh instances.

### SecurityResult is a generator handlers compose with

The shared tail becomes one generator that handlers `yield from` where the
protocol says a SecurityResult follows:

```python
def security_result(client) -> Generator[int, bytes, None]:
    (result,) = unpack("!I", (yield 4))
    ...
```

That is the payoff the callback chain cannot express. `None` on RFB < 3.8
simply does not `yield from` it; VeNCrypt's `X509None` does. The rule lives
next to the code that depends on it instead of at six call sites.

Failure handling (`_handleAuthFailed`, `_handleAuthFailedMessage`) folds into
the same generator — it is a length-prefixed read followed by
`client.vncAuthFailed(...)`.

## Scope of the first pass

Migrate **None, VNC Authentication (2), and ARD Diffie-Hellman (30)**, plus
the shared SecurityResult tail. This is pre-existing debt being paid before
new code lands on top of it.

**Leave VeNCrypt on the `expect` chain.** `_handleSecurityTypes` dispatches per
security type, so the registry and the old chain coexist: types with a handler
go through `_pump`, VeNCrypt keeps its `expect(self._handleVeNCryptVersion, 2)`
branch. VeNCrypt migrates separately, in the PR that introduces it (#498), once
this has landed.

Out of scope, deliberately:

- `_handleInitial`, `_handleNumberSecurityTypes`, `_handleSecurityTypes`,
  `_doClientInitialization`, `_handleServerInit`. Version negotiation and
  ClientInit are not security types.
- `_usableAuths` and the `max(valid_types)` choice. Selection policy stays put.
- The `input()`/`getpass()` calls in `ardRequestCredentials`, which block the
  reactor. Real, pre-existing, and not this change.
- The `AuthTypes.INVALID` / `_handleConnFailed` path from the RFB 3.3
  `_handleAuth`, which is a connection failure rather than a security type.

## What tells us it worked

`self._challenge`, `self.generator`, `self.keyLen`, `self.modulus` and
`self.serverKey` are gone from `RFBClient`, having become locals in the
handlers that use them. If they are still attributes at the end, the migration
recreated the trampoline with extra files.

`_pump`'s except clause catches decoder-flavoured exceptions
(`decoders.DecodeError`, `StructError`, `MemoryError`, `zlib.error`) and
reports `cannot decode {describe}`. A security handler wants its own verb and
its own error set; widen or parameterise rather than reporting a failed
handshake as a decode error.

## Testing

Unit tests only; `tests/unit/test_rfb.py` is the topical home and already
drives the handshake with a mocked transport. Behaviour must not move: the
existing auth tests should pass unchanged, and a diff that edits them is a
diff that changed behaviour. New tests cover the handlers directly — a
generator can be driven with `send()` without a transport at all, which is the
other reason to do this.

`tests/functional/` needs nothing new. The fleet already exercises None
(`tigervnc`) and VNC authentication (`tigervnc-auth`); ARD has no server to
test against, which is exactly why its tests must not be disturbed.
