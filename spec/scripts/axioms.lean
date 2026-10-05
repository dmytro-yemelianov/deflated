-- CI: the headline theorems must rest only on Lean's standard axioms.
-- Run with `lake env lean spec/scripts/axioms.lean`; CI fails on `sorryAx`.
-- Theorem names are added here by the task that proves them.
import Deflate
open Deflate
#print axioms Deflate.byteAt_oob
