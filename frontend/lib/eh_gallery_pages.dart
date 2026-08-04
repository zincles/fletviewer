import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'core_client.dart';

class EhGalleryPage extends StatefulWidget {
  const EhGalleryPage({
    super.key,
    required this.client,
    required this.summary,
    this.profile = 'default',
  });

  final CoreClient client;
  final EhGallerySummary summary;
  final String profile;

  @override
  State<EhGalleryPage> createState() => _EhGalleryPageState();
}

class _EhGalleryPageState extends State<EhGalleryPage> {
  EhGalleryDetail? _detail;
  EhThumbnailPage? _thumbnails;
  String? _error;
  String? _thumbnailError;
  bool _loading = true;
  bool _loadingThumbnails = false;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final detailFuture = widget.client.ehGalleryDetail(
      profile: widget.profile,
      gallery: widget.summary.gallery,
    );
    final thumbnailsFuture = widget.client.ehThumbnails(
      profile: widget.profile,
      gallery: widget.summary.gallery,
    );
    try {
      final results = await Future.wait<Object>([
        detailFuture,
        thumbnailsFuture,
      ]);
      if (!mounted) return;
      setState(() {
        _detail = results[0] as EhGalleryDetail;
        _thumbnails = results[1] as EhThumbnailPage;
        _loading = false;
        _thumbnailError = null;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '$error';
      });
    }
  }

  Future<void> _loadThumbnails(int page) async {
    if (_loadingThumbnails || page < 0) return;
    setState(() {
      _loadingThumbnails = true;
      _thumbnailError = null;
    });
    try {
      final thumbnails = await widget.client.ehThumbnails(
        profile: widget.profile,
        gallery: widget.summary.gallery,
        page: page,
      );
      if (!mounted) return;
      setState(() {
        _thumbnails = thumbnails;
        _loadingThumbnails = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _loadingThumbnails = false;
        _thumbnailError = '$error';
      });
    }
  }

  void _openReader(int page) {
    final detail = _detail;
    if (detail == null) return;
    unawaited(
      Navigator.of(context).push<void>(
        MaterialPageRoute(
          builder: (_) => EhReaderPage(
            client: widget.client,
            profile: widget.profile,
            detail: detail,
            initialPage: page,
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('E-Hentai 详情'),
        actions: [
          IconButton(
            tooltip: '刷新',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
          ? _GalleryLoadError(message: _error!, onRetry: _load)
          : _buildDetail(context, _detail!),
    );
  }

  Widget _buildDetail(BuildContext context, EhGalleryDetail detail) {
    final colors = Theme.of(context).colorScheme;
    return ListView(
      key: const Key('eh-gallery-detail'),
      padding: const EdgeInsets.only(bottom: 48),
      children: [
        ColoredBox(
          color: colors.surfaceContainerLow,
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1120),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 24, 20, 26),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      detail.title,
                      key: const Key('eh-detail-title'),
                      style: Theme.of(context).textTheme.headlineMedium
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    if (detail.subtitle case final subtitle?) ...[
                      const SizedBox(height: 6),
                      Text(
                        subtitle,
                        style: Theme.of(context).textTheme.titleMedium
                            ?.copyWith(color: colors.onSurfaceVariant),
                      ),
                    ],
                    const SizedBox(height: 16),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        _FactChip(
                          icon: Icons.menu_book_outlined,
                          label: '${detail.pageCount} 页',
                        ),
                        if (detail.rating case final rating?)
                          _FactChip(
                            icon: Icons.star_outline,
                            label:
                                '${rating.toStringAsFixed(2)} (${detail.ratingCount})',
                          ),
                        if (detail.language case final language?)
                          _FactChip(icon: Icons.translate, label: language),
                        if (detail.uploader case final uploader?)
                          _FactChip(
                            icon: Icons.person_outline,
                            label: uploader,
                          ),
                        if (detail.fileSize case final fileSize?)
                          _FactChip(icon: Icons.data_usage, label: fileSize),
                        _FactChip(
                          icon: detail.isFavorite
                              ? Icons.favorite
                              : Icons.favorite_border,
                          label: '${detail.favoriteCount}',
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),
                    FilledButton.icon(
                      key: const Key('eh-start-reader'),
                      onPressed: detail.pageCount == 0
                          ? null
                          : () => _openReader(0),
                      icon: const Icon(Icons.chrome_reader_mode_outlined),
                      label: const Text('开始阅读'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
        _DetailSection(
          title: '画廊信息',
          child: Wrap(
            spacing: 28,
            runSpacing: 12,
            children: [
              _MetadataField(label: 'GID', value: '${detail.gallery.gid}'),
              if (detail.posted case final posted?)
                _MetadataField(label: '发布时间', value: posted),
              if (detail.visible case final visible?)
                _MetadataField(label: '可见性', value: visible),
              _MetadataField(
                label: 'Session generation',
                value: '${detail.generation}',
              ),
            ],
          ),
        ),
        if (detail.tags.isNotEmpty)
          _DetailSection(
            title: '标签',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final namespace in detail.tags.entries) ...[
                  Text(
                    namespace.key,
                    style: Theme.of(context).textTheme.labelLarge?.copyWith(
                      color: colors.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      for (final tag in namespace.value)
                        Chip(
                          visualDensity: VisualDensity.compact,
                          label: Text(tag),
                        ),
                    ],
                  ),
                  const SizedBox(height: 14),
                ],
              ],
            ),
          ),
        _DetailSection(
          title: '页面',
          trailing: _loadingThumbnails
              ? const SizedBox.square(
                  dimension: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : null,
          child: _buildPages(context, detail),
        ),
        if (detail.comments.isNotEmpty)
          _DetailSection(
            title: '评论',
            child: Column(
              children: [
                for (
                  var index = 0;
                  index < detail.comments.length;
                  index++
                ) ...[
                  _CommentTile(comment: detail.comments[index]),
                  if (index + 1 < detail.comments.length)
                    const Divider(height: 24),
                ],
              ],
            ),
          ),
        if (detail.newerVersions.isNotEmpty)
          _DetailSection(
            title: '更新版本',
            child: Column(
              children: [
                for (final version in detail.newerVersions)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.history),
                    title: Text(version.title),
                    subtitle: version.posted == null
                        ? null
                        : Text(version.posted!),
                  ),
              ],
            ),
          ),
      ],
    );
  }

  Widget _buildPages(BuildContext context, EhGalleryDetail detail) {
    final page = _thumbnails;
    if (page == null) {
      return _GalleryLoadError(message: '未返回页面索引', onRetry: _load);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_thumbnailError != null) ...[
          _InlineMessage(message: _thumbnailError!),
          const SizedBox(height: 12),
        ],
        LayoutBuilder(
          builder: (context, constraints) {
            final columns = constraints.maxWidth >= 900
                ? 8
                : constraints.maxWidth >= 620
                ? 6
                : constraints.maxWidth >= 420
                ? 4
                : 3;
            return GridView.builder(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: columns,
                mainAxisSpacing: 8,
                crossAxisSpacing: 8,
                childAspectRatio: 1.25,
              ),
              itemCount: page.items.length,
              itemBuilder: (context, index) {
                final item = page.items[index];
                return _PageIndexTile(
                  page: item.page,
                  onTap: _loadingThumbnails
                      ? null
                      : () => _openReader(item.page),
                );
              },
            );
          },
        ),
        const SizedBox(height: 12),
        Row(
          mainAxisAlignment: MainAxisAlignment.end,
          children: [
            IconButton.outlined(
              tooltip: '上一组页面',
              onPressed: !_loadingThumbnails && page.page > 0
                  ? () => _loadThumbnails(page.page - 1)
                  : null,
              icon: const Icon(Icons.chevron_left),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Text('索引 ${page.page + 1}'),
            ),
            IconButton.filledTonal(
              tooltip: '下一组页面',
              onPressed: !_loadingThumbnails && page.nextPage != null
                  ? () => _loadThumbnails(page.nextPage!)
                  : null,
              icon: const Icon(Icons.chevron_right),
            ),
          ],
        ),
        if (page.items.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 24),
            child: Text(
              'fvcore 返回了空的页面索引。',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ),
      ],
    );
  }
}

class EhReaderPage extends StatefulWidget {
  const EhReaderPage({
    super.key,
    required this.client,
    required this.profile,
    required this.detail,
    required this.initialPage,
  });

  final CoreClient client;
  final String profile;
  final EhGalleryDetail detail;
  final int initialPage;

  @override
  State<EhReaderPage> createState() => _EhReaderPageState();
}

class _EhReaderPageState extends State<EhReaderPage> {
  late int _page;
  int _requestRevision = 0;
  CoreOperation? _operation;
  Uint8List? _bytes;
  String? _error;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _page = widget.initialPage;
    unawaited(_loadPage(_page));
  }

  Future<void> _loadPage(int page) async {
    if (page < 0 || page >= widget.detail.pageCount) return;
    final requestRevision = ++_requestRevision;
    setState(() {
      _page = page;
      _operation = null;
      _bytes = null;
      _error = null;
      _loading = true;
    });
    try {
      var operation = await widget.client.startEhPageFetch(
        profile: widget.profile,
        gallery: widget.detail.gallery,
        page: page,
      );
      _validateOperation(operation, page);
      if (!_isCurrent(requestRevision)) return;
      setState(() => _operation = operation);

      while (!operation.state.isTerminal) {
        await Future<void>.delayed(const Duration(milliseconds: 200));
        if (!_isCurrent(requestRevision)) return;
        operation = await widget.client.operation(operation.id);
        _validateOperation(operation, page);
        if (!_isCurrent(requestRevision)) return;
        setState(() => _operation = operation);
      }

      if (operation.state != CoreOperationState.completed) {
        final failure = operation.error;
        throw CoreTransportException(
          failure == null
              ? '图片获取已${operation.state.name}'
              : '${failure.code}: ${failure.message}',
        );
      }
      final resource = operation.resource;
      if (resource == null) {
        throw CoreTransportException('图片 operation 完成但没有返回 resource');
      }
      final bytes = await widget.client.imageResource(
        resource.contentMd5,
        resource.extension,
      );
      if (bytes.length != resource.byteLength) {
        throw CoreTransportException(
          '图片 resource 长度不匹配：期望 ${resource.byteLength}，实际 ${bytes.length}',
        );
      }
      if (!_isCurrent(requestRevision)) return;
      setState(() {
        _operation = operation;
        _bytes = bytes;
        _loading = false;
      });
    } on Object catch (error) {
      if (!_isCurrent(requestRevision)) return;
      setState(() {
        _error = '$error';
        _loading = false;
      });
    }
  }

  bool _isCurrent(int revision) => mounted && revision == _requestRevision;

  void _validateOperation(CoreOperation operation, int page) {
    if (!operation.belongsToEhPage(widget.detail.gallery, page)) {
      throw CoreTransportException('fvcore 返回了不属于当前画廊页的 operation');
    }
  }

  Future<void> _jumpToPage() async {
    final controller = TextEditingController(text: '${_page + 1}');
    final page = await showDialog<int>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('跳转到页面'),
        content: TextField(
          key: const Key('eh-reader-jump-input'),
          controller: controller,
          autofocus: true,
          keyboardType: TextInputType.number,
          decoration: InputDecoration(
            labelText: '页码',
            helperText: '1 - ${widget.detail.pageCount}',
          ),
          onSubmitted: (_) => _submitJump(context, controller.text),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => _submitJump(context, controller.text),
            child: const Text('跳转'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (page != null && mounted) unawaited(_loadPage(page));
  }

  void _submitJump(BuildContext dialogContext, String value) {
    final number = int.tryParse(value.trim());
    if (number == null || number < 1 || number > widget.detail.pageCount) {
      return;
    }
    Navigator.pop(dialogContext, number - 1);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xff101010),
      appBar: AppBar(
        backgroundColor: const Color(0xff181818),
        foregroundColor: Colors.white,
        title: Text(
          widget.detail.title,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
      ),
      body: Column(
        children: [
          Expanded(child: _buildReaderBody()),
          _ReaderNavigation(
            page: _page,
            pageCount: widget.detail.pageCount,
            enabled: !_loading,
            onPrevious: _page > 0 ? () => _loadPage(_page - 1) : null,
            onNext: _page + 1 < widget.detail.pageCount
                ? () => _loadPage(_page + 1)
                : null,
            onJump: _jumpToPage,
            onReload: () => _loadPage(_page),
          ),
        ],
      ),
    );
  }

  Widget _buildReaderBody() {
    final bytes = _bytes;
    if (bytes != null) {
      return InteractiveViewer(
        minScale: 0.5,
        maxScale: 8,
        boundaryMargin: const EdgeInsets.all(80),
        child: Center(
          child: Image.memory(
            bytes,
            key: const Key('eh-reader-image'),
            fit: BoxFit.contain,
            gaplessPlayback: true,
            filterQuality: FilterQuality.medium,
          ),
        ),
      );
    }
    if (_error case final error?) {
      return Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(
                  Icons.broken_image_outlined,
                  color: Colors.white70,
                  size: 52,
                ),
                const SizedBox(height: 14),
                Text(
                  error,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Colors.white),
                ),
                const SizedBox(height: 18),
                FilledButton.tonalIcon(
                  onPressed: () => _loadPage(_page),
                  icon: const Icon(Icons.refresh),
                  label: const Text('重试'),
                ),
              ],
            ),
          ),
        ),
      );
    }
    final operation = _operation;
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircularProgressIndicator(),
          const SizedBox(height: 16),
          Text(
            operation == null
                ? '正在创建图片操作'
                : '${operation.phase} · ${operation.bytesDone}${operation.bytesTotal == null ? '' : ' / ${operation.bytesTotal}'}',
            key: const Key('eh-reader-progress'),
            style: const TextStyle(color: Colors.white70),
          ),
        ],
      ),
    );
  }
}

class _ReaderNavigation extends StatelessWidget {
  const _ReaderNavigation({
    required this.page,
    required this.pageCount,
    required this.enabled,
    required this.onPrevious,
    required this.onNext,
    required this.onJump,
    required this.onReload,
  });

  final int page;
  final int pageCount;
  final bool enabled;
  final VoidCallback? onPrevious;
  final VoidCallback? onNext;
  final VoidCallback onJump;
  final VoidCallback onReload;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: SizedBox(
        height: 64,
        child: ColoredBox(
          color: const Color(0xff181818),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              IconButton(
                key: const Key('eh-reader-previous'),
                tooltip: '上一页',
                onPressed: enabled ? onPrevious : null,
                color: Colors.white,
                icon: const Icon(Icons.chevron_left),
              ),
              SizedBox(
                width: 112,
                child: TextButton(
                  key: const Key('eh-reader-page-counter'),
                  onPressed: enabled ? onJump : null,
                  child: Text('${page + 1} / $pageCount'),
                ),
              ),
              IconButton(
                key: const Key('eh-reader-next'),
                tooltip: '下一页',
                onPressed: enabled ? onNext : null,
                color: Colors.white,
                icon: const Icon(Icons.chevron_right),
              ),
              const SizedBox(width: 8),
              IconButton(
                tooltip: '重新加载',
                onPressed: enabled ? onReload : null,
                color: Colors.white,
                icon: const Icon(Icons.refresh),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DetailSection extends StatelessWidget {
  const _DetailSection({
    required this.title,
    required this.child,
    this.trailing,
  });

  final String title;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1120),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 26, 20, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      title,
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  trailing ?? const SizedBox.shrink(),
                ],
              ),
              const SizedBox(height: 14),
              child,
            ],
          ),
        ),
      ),
    );
  }
}

class _FactChip extends StatelessWidget {
  const _FactChip({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Chip(
      avatar: Icon(icon, size: 18),
      label: Text(label),
      visualDensity: VisualDensity.compact,
    );
  }
}

class _MetadataField extends StatelessWidget {
  const _MetadataField({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 220,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 2),
          Text(value, maxLines: 2, overflow: TextOverflow.ellipsis),
        ],
      ),
    );
  }
}

class _PageIndexTile extends StatelessWidget {
  const _PageIndexTile({required this.page, required this.onTap});

  final int page;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Material(
      color: colors.surfaceContainerHighest,
      borderRadius: BorderRadius.circular(6),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        key: Key('eh-thumbnail-$page'),
        onTap: onTap,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.image_outlined),
            const SizedBox(height: 4),
            Text('第 ${page + 1} 页'),
          ],
        ),
      ),
    );
  }
}

class _CommentTile extends StatelessWidget {
  const _CommentTile({required this.comment});

  final EhComment comment;

  @override
  Widget build(BuildContext context) {
    final score = comment.score;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.account_circle_outlined, size: 20),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                comment.userName,
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
            ),
            if (score != null) Text('评分 $score'),
          ],
        ),
        const SizedBox(height: 4),
        Text(
          comment.posted,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: 8),
        SelectableText(comment.content),
      ],
    );
  }
}

class _InlineMessage extends StatelessWidget {
  const _InlineMessage({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return ColoredBox(
      color: colors.errorContainer,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Text(message, style: TextStyle(color: colors.onErrorContainer)),
      ),
    );
  }
}

class _GalleryLoadError extends StatelessWidget {
  const _GalleryLoadError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.cloud_off_outlined,
                size: 52,
                color: Theme.of(context).colorScheme.error,
              ),
              const SizedBox(height: 14),
              Text(message, textAlign: TextAlign.center),
              const SizedBox(height: 18),
              FilledButton.tonalIcon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('重试'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
