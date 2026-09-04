from pathlib import Path

path = Path('.github/scripts/patch-submission-acceptance-race.py')
text = path.read_text()
old = '''source = replace_once(
    source,
    ''' + "'''" + '''              checkpoint => diagnostics.capture(page, `multipart-${index + 1}-${checkpoint}`),\\n              turn.abortSignal ? AbortSignal.any([stageSignal, turn.abortSignal]) : stageSignal,\\n            ),''' + "'''" + ''',
    ''' + "'''" + '''              checkpoint => diagnostics.capture(page, `multipart-${index + 1}-${checkpoint}`),\\n              turn.abortSignal ? AbortSignal.any([stageSignal, turn.abortSignal]) : stageSignal,\\n              recoverSubmissionObservation,\\n            ),''' + "'''" + ''',
    "multipart send recovery",
)
'''
new = '''multipart_anchor = source.index("`multipart_stage_${index + 1}_send`")
multipart_old = ''' + "'''" + '''              checkpoint => diagnostics.capture(page, `multipart-${index + 1}-${checkpoint}`),\\n              turn.abortSignal ? AbortSignal.any([stageSignal, turn.abortSignal]) : stageSignal,\\n            ),''' + "'''" + '''
multipart_new = ''' + "'''" + '''              checkpoint => diagnostics.capture(page, `multipart-${index + 1}-${checkpoint}`),\\n              turn.abortSignal ? AbortSignal.any([stageSignal, turn.abortSignal]) : stageSignal,\\n              recoverSubmissionObservation,\\n            ),''' + "'''" + '''
multipart_index = source.index(multipart_old, multipart_anchor)
source = source[:multipart_index] + multipart_new + source[multipart_index + len(multipart_old):]
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one multipart harness block, found {text.count(old)}')
path.write_text(text.replace(old, new, 1))
print('hardened temporary patch harness anchor')
