# Product

<!-- impeccable:product-schema 1 -->

## Platform

windows desktop

## Users

People who want a private, local workspace for dictation, document extraction, translation, and building a personal handwriting dataset.

## Product Purpose

Verbum keeps productivity workflows on-device. The Create Font surface lets a user collect, inspect, and safely stage handwriting samples for one named handwriting identity at a time.

## Positioning

Unlike cloud handwriting tools, Verbum processes samples locally and requires explicit review before new material can affect a font project's dataset.

## Operating Context

Windows 10/11 desktop application built with Python and PySide6. Users commonly add photographed handwriting sheets or single glyph images from local storage.

## Capabilities and Constraints

- Local-first and offline; no upload or remote model inference.
- Each font project has an isolated manifest, staging area, review data, history, and future output namespace.
- Phase 1 stages and reviews samples only; it does not generate TTF/OTF fonts or alter unrelated workflows.
- Existing legacy dataset remains preserved as one migrated project, not copied to every project.

## Brand Commitments

Verbum uses its existing dark desktop UI and concise, practical language.

## Evidence on Hand

- Existing baseline: `dataset/`, `metadata/glyph_manifest.json`, and reusable Step 2 pipeline under `tools/pipeline/`.
- Existing Create Font UI and worker architecture under `app/`.

## Product Principles

- Keep user data local and attributable.
- Prefer deterministic analysis with clear uncertainty over opaque guesses.
- Require a human decision before promotion to a verified dataset.
- Keep font identities completely separate.
