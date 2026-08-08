import 'dart:typed_data';

import 'package:flutter/material.dart';

/// Fades image bytes in once available and decodes at a bounded width.
///
/// All gallery covers render through this widget so scrolling stays smooth:
/// decoded bitmaps are capped via [cacheWidth] and appearance changes are
/// animated instead of popping.
class FadeInImageBox extends StatelessWidget {
  const FadeInImageBox({
    super.key,
    required this.bytes,
    required this.placeholder,
    this.fit = BoxFit.cover,
    this.cacheWidth = 640,
    this.placeholderFit = BoxFit.cover,
    this.imageKey,
  });

  final Uint8List? bytes;
  final Widget placeholder;
  final BoxFit fit;
  final BoxFit placeholderFit;
  final int cacheWidth;
  final Key? imageKey;

  @override
  Widget build(BuildContext context) {
    final current = bytes;
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 220),
      switchInCurve: Curves.easeOut,
      switchOutCurve: Curves.easeIn,
      child: current == null
          ? FittedBox(fit: placeholderFit, child: placeholder)
          : Image.memory(
              current,
              key: imageKey ?? ValueKey('bytes-${current.hashCode}'),
              fit: fit,
              cacheWidth: cacheWidth,
              gaplessPlayback: true,
              filterQuality: FilterQuality.medium,
            ),
    );
  }
}
