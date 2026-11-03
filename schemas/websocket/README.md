# Webex BYOVA WebSocket contract snapshot

These AsyncAPI files are preserved as an unmodified JSON contract snapshot from the public
[`webex/dataSourceSchemas`](https://github.com/webex/dataSourceSchemas) repository
at commit `c16938fcaea2eaee4270d2dede2b8704dbae0c8f` (retrieved 2026-09-08):

- `VoiceVirtualAgent_WsSchema.json`
- `VoiceVirtualAgent_WsListVASchema.json`

The datasource schema UUID is `a38a10b7-43e4-4676-a076-a7d6dce9387d`.

## Known upstream composition defect

`WsEnvelopeBase` sets `additionalProperties: false`. Derived envelope schemas
then use `allOf` to add `payload`, `code`, `status`, and `detail`. A strict JSON
Schema validator evaluates those derived fields against the closed base and
rejects the official examples as additional properties.

The gateway does not modify this evidence artifact. Runtime validation uses
strict concrete Pydantic envelope models in
`src/transports/websocket_models.py`. Those models express the intended examples
and simulator DTOs while still rejecting unknown fields.

When refreshing the snapshot, update both files, the pinned commit above, and
the contract tests together. Do not silently patch the vendor schema.
