import 'dart:io';

import 'package:fletviewer_frontend/runtime_launcher.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('storage identity formats unsigned 64-bit FNV values', () {
    expect(
      storageIdentity('temp', '/tmp/fletviewer-final-smoke/tmp/fvcore/Temp'),
      'v1-d69de1c83af0f00a',
    );
  });

  test('storage identity keeps low-bit hashes stable', () {
    expect(
      storageIdentity(
        'data',
        '/tmp/fletviewer-final-smoke/data/com.example.fletviewer_frontend/fvcore/Data',
      ),
      'v1-51f1b5ea12ef621d',
    );
  });

  test('generated bridge loader never resolves a CWD-relative crate build', () {
    // Regression guard: the FRB codegen default points the packaged loader at
    // `<crate>/target/release/` relative to the process CWD, which loaded a
    // stale library and caused content-hash mismatch. codegen.sh patches it;
    // this test fails if the generated file regresses.
    final generated = File(
      'lib/src/rust/frb_generated.dart',
    ).readAsStringSync();
    expect(
      generated,
      isNot(contains("ioDirectory: '../fvcore/target/release/'")),
    );
    expect(generated, contains('ioDirectory: null'));
  });
}
