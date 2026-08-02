import 'package:fletviewer_frontend/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('shows the fvcore connection surface', (tester) async {
    await tester.pumpWidget(const FletViewerApp());
    await tester.pump();

    expect(find.text('FletViewer · fvcore'), findsOneWidget);
    expect(find.textContaining('fvcore'), findsWidgets);
  });
}
