import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'core_client.dart';

void main() {
  runApp(const FletViewerApp());
}

class FletViewerApp extends StatelessWidget {
  const FletViewerApp({super.key, this.client});

  final CoreClient? client;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'FletViewer',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff7357d5)),
        useMaterial3: true,
      ),
      home: DownloadHome(client: client),
    );
  }
}

class DownloadHome extends StatefulWidget {
  const DownloadHome({super.key, this.client});

  final CoreClient? client;

  @override
  State<DownloadHome> createState() => _DownloadHomeState();
}

class _DownloadHomeState extends State<DownloadHome> {
  late final CoreClient _client;
  CoreSnapshot? _runtime;
  List<DownloadTask> _tasks = const [];
  StreamSubscription<CoreEventSignal>? _events;
  Timer? _reconnect;
  bool _loading = true;
  String? _error;
  int _cursor = 0;
  final Map<String, int> _taskRevisions = {};

  @override
  void initState() {
    super.initState();
    _client = widget.client ?? CoreClient(Uri.parse('http://127.0.0.1:8787'));
    unawaited(_connect());
  }

  @override
  void dispose() {
    _reconnect?.cancel();
    unawaited(_events?.cancel());
    if (widget.client == null) _client.close();
    super.dispose();
  }

  Future<void> _connect() async {
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final runtime = await _client.runtime();
      final tasks = await _client.downloadTasks();
      if (!mounted) return;
      setState(() {
        _runtime = runtime;
        _tasks = tasks;
        _loading = false;
      });
      _listen(runtime.runtimeId);
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '$error';
      });
    }
  }

  void _listen(String runtimeId) {
    unawaited(_events?.cancel());
    _events = _client
        .events(cursor: _cursor)
        .listen(
          (signal) async {
            if (signal is CoreResyncRequired) {
              _cursor = 0;
              await _reloadAll();
              return;
            }
            final event = (signal as CoreInvalidated).event;
            if (event.runtimeId != runtimeId) {
              _cursor = 0;
              await _connect();
              return;
            }
            _cursor = event.sequence;
            final id = event.taskId;
            if (id == null || event.revision <= (_taskRevisions[id] ?? 0)) {
              return;
            }
            _taskRevisions[id] = event.revision;
            await _reloadTask(id);
          },
          onError: (_) => _scheduleReconnect(),
          onDone: _scheduleReconnect,
          cancelOnError: true,
        );
  }

  void _scheduleReconnect() {
    if (!mounted || _reconnect?.isActive == true) return;
    _reconnect = Timer(const Duration(seconds: 1), () {
      final runtimeId = _runtime?.runtimeId;
      if (runtimeId != null) _listen(runtimeId);
    });
  }

  Future<void> _reloadAll() async {
    try {
      final tasks = await _client.downloadTasks();
      if (mounted) setState(() => _tasks = tasks);
    } on Object catch (error) {
      if (mounted) setState(() => _error = '$error');
    }
  }

  Future<void> _reloadTask(String id) async {
    try {
      final task = await _client.downloadTask(id);
      if (!mounted) return;
      setState(() {
        final tasks = [..._tasks];
        final index = tasks.indexWhere((candidate) => candidate.id == id);
        if (index == -1) {
          tasks.add(task);
        } else {
          tasks[index] = task;
        }
        tasks.sort((left, right) => left.createdAt.compareTo(right.createdAt));
        _tasks = List.unmodifiable(tasks);
      });
    } on CoreApiException catch (error) {
      if (error.statusCode == 404) await _reloadAll();
    }
  }

  Future<void> _command(
    DownloadTask task,
    Future<Object?> Function() command,
  ) async {
    try {
      await command();
      await _reloadAll();
    } on Object catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('$error')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('FletViewer · fvcore'),
        actions: [
          IconButton(
            tooltip: '刷新',
            onPressed: _connect,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _ConnectionBanner(runtime: _runtime, error: _error),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _tasks.isEmpty
                ? const Center(child: Text('暂无下载任务'))
                : ListView.separated(
                    padding: const EdgeInsets.all(16),
                    itemCount: _tasks.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 10),
                    itemBuilder: (context, index) {
                      final task = _tasks[index];
                      return _DownloadTaskCard(
                        task: task,
                        onCancel: task.canCancel
                            ? () => _command(
                                task,
                                () => _client.cancelDownloadTask(task.id),
                              )
                            : null,
                        onRetry: task.canRetry
                            ? () => _command(
                                task,
                                () => _client.retryDownloadTask(task.id),
                              )
                            : null,
                        onDelete: task.canDelete
                            ? () => _command(
                                task,
                                () => _client.deleteDownloadTask(task.id),
                              )
                            : null,
                        loadImage: () => _loadTaskImage(task),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }

  Future<Uint8List?> _loadTaskImage(DownloadTask task) async {
    final md5 = task.metadata['content_md5'];
    if (md5 is! String || md5.isEmpty) return null;
    final extension = task.filename.split('.').last;
    if (extension == task.filename || extension.isEmpty) return null;
    return _client.imageResource(md5, extension);
  }
}

class _ConnectionBanner extends StatelessWidget {
  const _ConnectionBanner({required this.runtime, required this.error});

  final CoreSnapshot? runtime;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final connected = runtime?.state == 'ready' && error == null;
    return ColoredBox(
      color: connected ? colors.secondaryContainer : colors.errorContainer,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
        child: Text(
          connected
              ? '已连接 ${runtime!.instanceName} · Core ${runtime!.coreVersion} · API v${runtime!.apiProtocolVersion}'
              : error ?? '正在连接 fvcore…',
        ),
      ),
    );
  }
}

class _DownloadTaskCard extends StatelessWidget {
  const _DownloadTaskCard({
    required this.task,
    required this.onCancel,
    required this.onRetry,
    required this.onDelete,
    required this.loadImage,
  });

  final DownloadTask task;
  final VoidCallback? onCancel;
  final VoidCallback? onRetry;
  final VoidCallback? onDelete;
  final Future<Uint8List?> Function() loadImage;

  @override
  Widget build(BuildContext context) {
    final progress = task.progress;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 88,
              height: 88,
              child: FutureBuilder<Uint8List?>(
                future: loadImage(),
                builder: (context, snapshot) {
                  final bytes = snapshot.data;
                  if (bytes == null) {
                    return const ColoredBox(
                      color: Color(0x11000000),
                      child: Icon(Icons.image_outlined),
                    );
                  }
                  return Image.memory(
                    bytes,
                    fit: BoxFit.cover,
                    gaplessPlayback: true,
                  );
                },
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    task.title,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${task.provider} · ${task.kind} · ${task.status.name} · ${task.phase}',
                  ),
                  if (progress != null) ...[
                    const SizedBox(height: 10),
                    LinearProgressIndicator(value: progress),
                  ],
                  if (task.error.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(
                      task.error,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ],
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    children: [
                      if (onCancel != null)
                        TextButton(
                          onPressed: onCancel,
                          child: const Text('取消'),
                        ),
                      if (onRetry != null)
                        FilledButton.tonal(
                          onPressed: onRetry,
                          child: const Text('重试'),
                        ),
                      if (onDelete != null)
                        TextButton(
                          onPressed: onDelete,
                          child: const Text('删除'),
                        ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
