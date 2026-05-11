# CookPlanStudio Releases

Public distribution channel for [CookPlanStudio](https://github.com/hotmessdev/CookPlanMobile), a macOS authoring tool for competition BBQ cook plans.

This repo exists **only to host DMG releases and the Sparkle appcast feed**. Studio's source code lives in the private `CookPlanMobile` repo and is not mirrored here.

## Downloads

[Latest release →](https://github.com/hotmessdev/CookPlanStudio-releases/releases/latest)

All releases are **notarized + stapled** by Apple's Developer ID program. Each DMG is also signed for [Sparkle](https://sparkle-project.org) auto-update verification — installed copies of CookPlanStudio v1.20.3 and later check this repo's [`docs/appcast.xml`](docs/appcast.xml) feed daily and offer one-click in-app upgrades.

## System requirements

- macOS 15 (Sequoia) or later
- ~10 MB free disk

## Installation

1. Download the latest `CookPlanStudio-X.Y.Z.dmg` from the Releases page above.
2. Double-click the DMG.
3. Drag `CookPlanStudio.app` to `/Applications`.
4. First launch: macOS Gatekeeper validates the Apple notarization staple offline — no internet round-trip required.

## Auto-update

CookPlanStudio v1.20.3 and later auto-checks this feed once per day in the background and on demand via `CookPlanStudio → Check for Updates…`. Updates are downloaded, EdDSA-signature-verified against the public key embedded in the running app, and applied with one click.

Versions v1.20.0, v1.20.1, and v1.20.2 shipped with non-functional Sparkle feed URLs and cannot auto-update — see those releases' notes for the manual upgrade path.

## License

Distribution-only repo; release assets are © hotmessdev. Source is private.
