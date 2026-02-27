<?php
/**
 * MI_Barcode — PDF Label Generator
 *
 * Uses TCPDF for inch-precise label layouts.
 * Supports two print modes:
 *
 *   Thermal mode  — labels_per_row=1, labels_per_column=1
 *                   Each label gets its own PDF page sized exactly to the label.
 *
 *   Sheet mode    — labels_per_row > 1 or labels_per_column > 1
 *                   Labels are tiled on 8.5" × 11" pages using the profile's
 *                   margin and spacing values.
 *
 * Dimension math:
 *   TCPDF's internal unit is mm. All profile values (stored in inches) are
 *   multiplied by MM_PER_INCH (25.4) before being passed to TCPDF.
 *   Example: 4" wide label → 4 × 25.4 = 101.6 mm.
 *
 * Barcode (Code 39 / C39):
 *   Code 39 uses '*' as start/stop delimiters — the final barcode encodes
 *   *{DATA}*. TCPDF adds these automatically when you pass format 'C39',
 *   so we pass the plain UPC string. The scanner will read *764083XXXXXX*.
 *   For Code 128 ('C128'), no asterisks are used; pass the plain UPC.
 */

declare(strict_types=1);

require_once APP_ROOT . '/lib/TCPDF-main/tcpdf.php';

const MM_PER_INCH = 25.4;

// ── Public entry point ────────────────────────────────────────────────────────

/**
 * Generate a PDF of labels and stream it inline to the browser (new tab).
 *
 * @param array  $item    DB row: upc, description, uom, part_number, model_number, sku
 * @param array  $profile DB row from label_profiles
 * @param int    $qty     Number of labels to produce
 * @param string $fmt     TCPDF barcode format; defaults to DEFAULT_BARCODE_FORMAT
 */
function generateLabelsPDF(
    array  $item,
    array  $profile,
    int    $qty,
    string $fmt = DEFAULT_BARCODE_FORMAT
): void {
    // ── Convert profile inches → mm ──────────────────────────────────────────
    $labelW = (float)$profile['label_width_inches']  * MM_PER_INCH;
    $labelH = (float)$profile['label_height_inches'] * MM_PER_INCH;
    $mTop   = (float)$profile['margin_top']          * MM_PER_INCH;
    $mLeft  = (float)$profile['margin_left']         * MM_PER_INCH;
    $hGap   = (float)$profile['horizontal_spacing']  * MM_PER_INCH;
    $vGap   = (float)$profile['vertical_spacing']    * MM_PER_INCH;
    $cols   = max(1, (int)$profile['labels_per_row']);
    $rows   = max(1, (int)$profile['labels_per_column']);
    $perPage = $cols * $rows;

    // Thermal = exactly one label per page
    $isThermal = ($cols === 1 && $rows === 1);

    // ── Page dimensions ───────────────────────────────────────────────────────
    if ($isThermal) {
        $pageW = $labelW;
        $pageH = $labelH;
    } else {
        $pageW = 8.5 * MM_PER_INCH;   // 215.9 mm
        $pageH = 11.0 * MM_PER_INCH;  // 279.4 mm
    }
    $orientation = ($pageW > $pageH) ? 'L' : 'P';

    // ── Barcode data ──────────────────────────────────────────────────────────
    // Pass the plain UPC (uppercase). TCPDF's C39 encoder auto-wraps with *.
    $barcodeData = strtoupper(trim((string)$item['upc']));

    // ── Logo ──────────────────────────────────────────────────────────────────
    $logoPath = APP_ROOT . '/assets/img/logo.png';
    $hasLogo  = file_exists($logoPath) && filesize($logoPath) > 200;

    // ── Initialise TCPDF ──────────────────────────────────────────────────────
    $pdf = new TCPDF($orientation, 'mm', [$pageW, $pageH], true, 'UTF-8', false);
    $pdf->SetCreator(APP_NAME);
    $pdf->SetAuthor('MI');
    $pdf->SetTitle('Labels – ' . $item['upc']);
    $pdf->SetMargins(0, 0, 0, true);
    $pdf->SetHeaderMargin(0);
    $pdf->SetFooterMargin(0);
    $pdf->SetAutoPageBreak(false, 0);
    $pdf->setPrintHeader(false);
    $pdf->setPrintFooter(false);

    // ── Render labels ─────────────────────────────────────────────────────────
    $placed = 0; // labels placed on the current sheet page

    for ($i = 0; $i < $qty; $i++) {
        if ($isThermal) {
            // Each label is its own page.
            $pdf->AddPage();
            _renderLabel($pdf, $item, $labelW, $labelH, 0.0, 0.0,
                         $barcodeData, $fmt, $hasLogo, $logoPath);
        } else {
            // Start a fresh sheet when the current one is full.
            if ($placed % $perPage === 0) {
                $pdf->AddPage();
            }

            // Calculate which grid cell this label occupies.
            $posOnPage = $placed % $perPage;
            $col       = $posOnPage % $cols;
            $row       = intdiv($posOnPage, $cols);

            // Convert grid position to mm coordinates on the page.
            $x = $mLeft + $col * ($labelW + $hGap);
            $y = $mTop  + $row * ($labelH + $vGap);

            _renderLabel($pdf, $item, $labelW, $labelH, $x, $y,
                         $barcodeData, $fmt, $hasLogo, $logoPath);
            $placed++;
        }
    }

    // Stream inline → opens in new browser tab.
    $pdf->Output('labels_' . $item['upc'] . '.pdf', 'I');
}

// ── Internal label renderer ───────────────────────────────────────────────────

/**
 * Draw one label at absolute position (x, y) on the current TCPDF page.
 *
 * Label layout (top → bottom):
 *   1. MI Logo        — 20% of label height (omitted when logo.png is missing)
 *   2. Description    — 22% of label height  (bold text, wraps if needed)
 *   3. UOM + Part #   — 13% of label height  (single line)
 *   4. Barcode        — remaining height (~45%), minimum 4 mm to render
 *
 * Font sizes are derived from each section's pixel height but clamped to
 * sane min/max values so tiny thermal labels and large sheet labels both
 * look reasonable.
 *
 * @param float $lW  Label width (mm)
 * @param float $lH  Label height (mm)
 * @param float $x   Label origin X on the page (mm)
 * @param float $y   Label origin Y on the page (mm)
 */
function _renderLabel(
    TCPDF  $pdf,
    array  $item,
    float  $lW,
    float  $lH,
    float  $x,
    float  $y,
    string $barcodeData,
    string $fmt,
    bool   $hasLogo,
    string $logoPath
): void {
    // ── Padding ───────────────────────────────────────────────────────────────
    // 4% of label width, capped at 2 mm so tiny labels keep breathing room.
    $pad   = min(2.0, $lW * 0.04);
    $inner = $lW - ($pad * 2); // usable inner width
    $ix    = $x + $pad;        // inner X origin
    $cy    = $y + $pad;        // Y cursor (advances downward)

    // ── Section heights ───────────────────────────────────────────────────────
    $logoSec = $hasLogo ? $lH * 0.20 : 0.0;
    $descSec = $lH * 0.22;
    $infoSec = $lH * 0.13;
    // Barcode fills whatever remains after the text sections and padding.
    $barcSec = $lH - $logoSec - $descSec - $infoSec - ($pad * 2);

    // ── 1. Logo ───────────────────────────────────────────────────────────────
    if ($hasLogo) {
        // Cap logo width at 60% of inner or 30 mm. Height=0 → auto aspect ratio.
        $maxLogoW = min($inner * 0.60, 30.0);
        $pdf->Image(
            $logoPath, $ix, $cy,
            $maxLogoW, 0,     // width, height (0 = auto)
            'PNG', '', 'T',   // type, link, align
            false, 300,       // resize, dpi
            '', false, false, // x-link, fitbox, hidden
            0, 'L'            // border, position
        );
        $cy += $logoSec;
    }

    // ── 2. Description ────────────────────────────────────────────────────────
    // Font: bold, clamped 6–11 pt, derived from section height.
    $descFontSize = (int) max(6.0, min(11.0, $descSec * 0.90));
    $pdf->SetFont('helvetica', 'B', $descFontSize);
    $pdf->SetXY($ix, $cy);
    // MultiCell wraps long descriptions; AutoPageBreak is off so it clips cleanly.
    $pdf->MultiCell($inner, $descSec, (string)($item['description'] ?? ''),
                    0, 'L', false, 1);
    $cy += $descSec;

    // ── 3. UOM + Part number ──────────────────────────────────────────────────
    // Priority: SKU → part_number → model_number (see getDisplayPartNumber()).
    $infoFontSize = (int) max(5.0, min(9.0, $infoSec * 0.90));
    $pdf->SetFont('helvetica', '', $infoFontSize);
    $pdf->SetXY($ix, $cy);

    $parts = [];
    if (!empty($item['uom'])) {
        $parts[] = 'UOM: ' . $item['uom'];
    }
    $pn = getDisplayPartNumber($item);
    if ($pn !== 'N/A') {
        $parts[] = '#: ' . $pn;
    }
    $pdf->Cell($inner, $infoSec, implode('  |  ', $parts), 0, 0, 'L');
    $cy += $infoSec;

    // ── 4. Barcode ────────────────────────────────────────────────────────────
    // Skip if there isn't at least 4 mm of vertical space left.
    if ($barcSec >= 4.0) {
        $barcodeStyle = [
            'position'     => '',
            'align'        => 'C',
            'stretch'      => false,
            'fitwidth'     => true,    // expand/shrink bars to fill $inner width
            'cellfitalign' => '',
            'border'       => false,
            'padding'      => 0,
            'fgcolor'      => [0, 0, 0],
            'bgcolor'      => false,
            'text'         => true,    // print human-readable digits below bars
            'font'         => 'helvetica',
            'fontsize'     => max(5, (int)($barcSec * 0.14)),
            'stretchtext'  => 4,
        ];

        // Reserve ~15% of barcode section height for the human-readable line.
        $barH = $barcSec * 0.85;

        $pdf->write1DBarcode(
            $barcodeData,  // plain UPC; TCPDF wraps with * for C39 → *{UPC}*
            $fmt,          // 'C39', 'C128', or 'UPCA'
            $ix,           // x
            $cy,           // y
            $inner,        // w — spans full inner width
            $barH,         // h
            0.4,           // xres — narrowest bar width in mm
            $barcodeStyle,
            'N'            // position flag: N = use the x,y above
        );
    }
}
