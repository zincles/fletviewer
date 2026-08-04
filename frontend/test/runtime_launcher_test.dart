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
}
