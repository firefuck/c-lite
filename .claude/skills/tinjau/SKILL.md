---
name: tinjau
description: Meninjau hasil sebuah task roadmap di konteks bersih dan melaporkan temuan. Pakai setelah task selesai dikerjakan, misalnya /tinjau F2-T4.
argument-hint: "[nomor-task]"
disable-model-invocation: true
context: fork
agent: peninjau
background: false
---

Baca `docs/prompts/03-tinjau.md` dan jalankan bagian "Prompt" di dalamnya, dengan `<TASK>` diganti:

$ARGUMENTS
