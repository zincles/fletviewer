import 'package:fletviewer_frontend/main.dart';
import 'dart:async';
import 'dart:typed_data';

import 'package:fletviewer_frontend/core_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late _FakeCoreClient client;

  setUp(() => client = _FakeCoreClient());
  testWidgets('shows the responsive Flet-style browse shell', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();

    expect(find.text('FletViewer · 实验性 GUI · 发现'), findsOneWidget);
    expect(find.text('E-Hentai'), findsWidgets);
    expect(find.text('主页'), findsWidgets);
    expect(find.byType(SearchBar), findsOneWidget);
    expect(find.text('Rust 查询 fixture'), findsOneWidget);
  });

  testWidgets('mobile navigation opens downloads without overflow', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(420, 820);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();
    expect(find.text('实验性 GUI · 发现'), findsOneWidget);
    await tester.tap(find.byKey(const Key('nav-downloads')));
    await tester.pumpAndSettle();

    expect(find.text('实验性 GUI · 下载任务'), findsOneWidget);
    expect(find.text('暂无下载任务'), findsOneWidget);
    expect(find.textContaining('fvcore'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('connection chip reveals the development launcher notice', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(420, 820);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();
    await tester.tap(find.byKey(const Key('core-status-button')));
    await tester.pump();

    expect(find.byKey(const Key('core-help-banner')), findsOneWidget);
    expect(find.textContaining('flutter_rust_bridge'), findsOneWidget);
  });
}

final class _FakeCoreClient implements CoreClient {
  static const snapshot = CoreSnapshot(
    apiProtocolVersion: 1,
    coreVersion: '0.1.0-test',
    runtimeId: 'runtime-test',
    instanceName: 'fvcore',
    state: 'ready',
    storage: StorageSnapshot(
      schemaVersion: 3,
      dataIdentity: 'data-test',
      cacheIdentity: 'cache-test',
      downloadsIdentity: 'downloads-test',
      tempIdentity: 'temp-test',
      databaseBytes: 4096,
    ),
  );

  @override
  Future<CoreSnapshot> runtime() async => snapshot;

  @override
  Future<List<DownloadTask>> downloadTasks() async => const [];

  @override
  Future<EhHomePage> ehSearch({
    String profile = 'default',
    String search = '',
    EhPageCursor? cursor,
  }) async {
    return const EhHomePage(
      profile: 'default',
      generation: 1,
      galleries: [
        EhGallerySummary(
          gallery: EhGalleryRef(gid: 123, token: 'fixture-token'),
          pageUrl: 'https://e-hentai.org/g/123/fixture-token/',
          title: 'Rust 查询 fixture',
          category: 'Manga',
          published: null,
          uploader: 'fixture',
          pageCount: 24,
          rating: 4.5,
          language: 'Chinese',
          tags: ['artist:fixture'],
          coverUrl: null,
          coverWidth: null,
          coverHeight: null,
        ),
      ],
      previous: null,
      next: null,
    );
  }

  @override
  Future<DownloadTask> downloadTask(String id) async =>
      throw UnimplementedError();

  @override
  Future<DownloadTask> cancelDownloadTask(String id) async =>
      throw UnimplementedError();

  @override
  Future<DownloadTask> retryDownloadTask(String id) async =>
      throw UnimplementedError();

  @override
  Future<void> deleteDownloadTask(String id) async =>
      throw UnimplementedError();

  @override
  Future<Uint8List> imageResource(String contentMd5, String extension) async =>
      Uint8List(0);

  @override
  Stream<CoreEventSignal> events({int cursor = 0}) async* {
    await Completer<void>().future;
  }

  @override
  Future<void> close() async {}
}
