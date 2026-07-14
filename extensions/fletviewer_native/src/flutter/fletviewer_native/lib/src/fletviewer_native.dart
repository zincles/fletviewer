import 'package:flet/flet.dart';
import 'package:flutter/material.dart';

class FletviewerImageReaderControl extends StatefulWidget {
  final Control control;

  const FletviewerImageReaderControl({
    super.key,
    required this.control,
  });

  @override
  State<FletviewerImageReaderControl> createState() =>
      _FletviewerImageReaderControlState();
}

class _FletviewerImageReaderControlState
    extends State<FletviewerImageReaderControl> {
  late PageController _pageController;
  late int _initialIndex;

  List<String> get _urls => widget.control.getList<String>(
        "urls",
        (value) => value.toString(),
        defaultValue: const [],
      )!;

  @override
  void initState() {
    super.initState();
    _initialIndex = _normalizedInitialIndex();
    _pageController = PageController(initialPage: _initialIndex);
  }

  @override
  void didUpdateWidget(covariant FletviewerImageReaderControl oldWidget) {
    super.didUpdateWidget(oldWidget);
    final nextIndex = _normalizedInitialIndex();
    if (nextIndex != _initialIndex && _pageController.hasClients) {
      _initialIndex = nextIndex;
      _pageController.jumpToPage(nextIndex);
    }
  }

  int _normalizedInitialIndex() {
    final urls = _urls;
    if (urls.isEmpty) return 0;
    return widget.control.getInt("initial_index", 0)!.clamp(0, urls.length - 1);
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final urls = _urls;
    final minScale = widget.control.getDouble("min_scale", 1.0)!;
    final maxScale = widget.control.getDouble("max_scale", 4.0)!;

    Widget reader;
    if (urls.isEmpty) {
      reader = const Center(child: Icon(Icons.image_not_supported_outlined));
    } else {
      reader = PageView.builder(
        controller: _pageController,
        itemCount: urls.length,
        onPageChanged: (index) => widget.control.triggerEvent("change", index),
        itemBuilder: (context, index) => InteractiveViewer(
          minScale: minScale,
          maxScale: maxScale,
          child: Center(
            child: Image.network(
              urls[index],
              key: ValueKey(urls[index]),
              fit: BoxFit.contain,
              frameBuilder: (context, child, frame, wasSynchronouslyLoaded) {
                if (wasSynchronouslyLoaded || frame != null) return child;
                return const Center(child: CircularProgressIndicator());
              },
              errorBuilder: (context, error, stackTrace) => const Center(
                child: Icon(Icons.broken_image_outlined, size: 48),
              ),
            ),
          ),
        ),
      );
    }

    return LayoutControl(control: widget.control, child: reader);
  }
}
