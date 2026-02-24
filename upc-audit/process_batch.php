<?php
// Prevent any output before JSON
ob_start();

require_once 'db_config.php';

// Check if this is an AJAX request
$is_ajax = isset($_POST['ajax']) && $_POST['ajax'] === '1';

// ─── Handle "Reset Errors to Pending" action ───
if (isset($_POST['reset_errors'])) {
    $source = $_POST['error_source'] ?? '';
    if (!empty($source)) {
        $stmt = $pdo->prepare("UPDATE upc_lookups SET match_status = 'pending', api_source = NULL, product_name = NULL, api_response = NULL WHERE match_status = 'error' AND api_source = ?");
        $stmt->execute([$source]);
        $count = $stmt->rowCount();
    } else {
        $count = $pdo->exec("UPDATE upc_lookups SET match_status = 'pending', api_source = NULL, product_name = NULL, api_response = NULL WHERE match_status = 'error'");
    }
    if ($is_ajax) {
        ob_end_clean();
        header('Content-Type: application/json');
        echo json_encode(['status' => 'reset', 'count' => $count]);
        exit;
    }
    header('Location: index.php?reset=' . $count);
    exit;
}

// API Configuration
$api_configs = [
    'barcodelookup' => [
        'key' => '1fu4ju8dcw372vgm9m7xckxfm7w8zf',
        'url' => 'https://api.barcodelookup.com/v3/products',
        'delay' => 500000
    ],
    'upcitemdb' => [
        'key' => 'cd4f644bb63b8e53b8cb2cd2becc599f',
        'url' => 'https://api.upcitemdb.com/prod/v1/lookup',
        'delay' => 2200000, // 2.2s — slightly above sustainable rate
        'batch_size' => 10
    ]
];

// Get parameters
$api_source = $_POST['api_source'] ?? '';
$batch_size = (int)($_POST['batch_size'] ?? 10);
$retry_errors = isset($_POST['retry_errors']) && $_POST['retry_errors'] === '1';

if (empty($api_source) || !isset($api_configs[$api_source])) {
    if ($is_ajax) {
        ob_end_clean();
        header('Content-Type: application/json');
        echo json_encode(['error' => 'Please select an API source']);
        exit;
    } else {
        die("Please select an API source");
    }
}

$config = $api_configs[$api_source];

// Get records to process
$batch_size_int = max(1, intval($batch_size));

if ($retry_errors) {
    $stmt = $pdo->prepare("SELECT * FROM upc_lookups WHERE match_status = 'error' AND api_source = ? LIMIT " . $batch_size_int);
    $stmt->execute([$api_source]);
} else {
    $stmt = $pdo->query("SELECT * FROM upc_lookups WHERE match_status = 'pending' LIMIT " . $batch_size_int);
}

$pending = $stmt->fetchAll();

if (empty($pending)) {
    if ($is_ajax) {
        ob_end_clean();
        header('Content-Type: application/json');
        echo json_encode([
            'status' => 'complete',
            'processed' => 0,
            'message' => 'No more records to process'
        ]);
        exit;
    } else {
        header('Location: index.php?message=No records to process');
        exit;
    }
}

$processed = 0;
$errors = 0;
$found = 0;
$not_found = 0;
$rate_limited = false;
$rate_limit_remaining = null;

$update_stmt = $pdo->prepare("
    UPDATE upc_lookups 
    SET product_name = ?, brand = ?, model = ?, asin = ?, country = ?, category = ?,
        size = ?, color = ?, weight = ?, dimensions = ?, lowest_price = ?, price_currency = ?,
        image_url = ?, retailer_data = ?, api_response = ?, match_status = ?,
        api_source = ?, last_scanned = ?, lookup_date = NOW()
    WHERE id = ?
");

// Helper: extract product data from upcitemdb item
function extractUpcitemdbProduct($product) {
    $product_name = $product['title'] ?? 'Unknown Product';
    $brand = $product['brand'] ?? null;
    $model = $product['model'] ?? null;
    $asin = $product['asin'] ?? null;
    $category = $product['category'] ?? null;
    $country = $product['country'] ?? null;
    $size = $product['size'] ?? null;
    $color = $product['color'] ?? null;
    $weight = $product['weight'] ?? null;
    $dimensions = $product['dimension'] ?? null;
    
    $last_scanned = null;
    if (isset($product['last_update'])) {
        $last_scanned = date('Y-m-d H:i:s', strtotime($product['last_update']));
    }
    
    $image_url = null;
    if (isset($product['images']) && is_array($product['images']) && count($product['images']) > 0) {
        $image_url = $product['images'][0];
    }
    
    $retailers = [];
    $lowest_price = $product['lowest_recorded_price'] ?? null;
    $price_currency = 'USD';
    
    if (isset($product['offers']) && is_array($product['offers'])) {
        foreach ($product['offers'] as $offer) {
            if (isset($offer['domain'])) {
                $retailers[] = $offer['domain'];
            }
            if (isset($offer['price']) && !empty($offer['price'])) {
                $price = floatval($offer['price']);
                if ($lowest_price === null || $price < $lowest_price) {
                    $lowest_price = $price;
                }
            }
        }
    }
    $retailer_data = !empty($retailers) ? implode(', ', $retailers) : 'No retailers listed';
    
    return compact('product_name', 'brand', 'model', 'asin', 'country', 'category',
        'size', 'color', 'weight', 'dimensions', 'lowest_price', 'price_currency',
        'image_url', 'retailer_data', 'last_scanned');
}

// Helper: parse rate limit headers
function parseRateLimitHeaders($header_text) {
    $headers = [];
    foreach (explode("\r\n", $header_text) as $line) {
        if (stripos($line, 'X-RateLimit-') === 0) {
            $parts = explode(':', $line, 2);
            if (count($parts) === 2) {
                $headers[strtolower(trim($parts[0]))] = trim($parts[1]);
            }
        }
    }
    return $headers;
}

if ($api_source === 'upcitemdb') {
    // ─── BATCH MODE: up to 10 UPCs per API call ───
    $api_batch_size = $config['batch_size'];
    $chunks = array_chunk($pending, $api_batch_size);
    
    foreach ($chunks as $chunk) {
        if ($rate_limited) break;
        
        $upc_list = [];
        $upc_to_items = [];
        foreach ($chunk as $item) {
            $upc = $item['upc'];
            $upc_list[] = $upc;
            $upc_to_items[$upc] = $item;
        }
        $upc_param = implode(',', $upc_list);
        
        $response_headers = '';
        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $config['url'] . '?upc=' . urlencode($upc_param));
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 30);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
        curl_setopt($ch, CURLOPT_ENCODING, 'gzip,deflate');
        curl_setopt($ch, CURLOPT_HTTPHEADER, [
            'Accept: application/json',
            'Accept-Encoding: gzip,deflate',
            'user_key: ' . $config['key'],
            'key_type: 3scale'
        ]);
        curl_setopt($ch, CURLOPT_HEADERFUNCTION, function($curl, $header) use (&$response_headers) {
            $response_headers .= $header;
            return strlen($header);
        });
        
        $response = curl_exec($ch);
        $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $curl_error = curl_error($ch);
        curl_close($ch);
        
        // Parse rate limit headers
        $rate_headers = parseRateLimitHeaders($response_headers);
        if (isset($rate_headers['x-ratelimit-remaining'])) {
            $rate_limit_remaining = intval($rate_headers['x-ratelimit-remaining']);
        }
        
        // ─── 429: Stop immediately, leave records untouched ───
        if ($http_code === 429) {
            $rate_limited = true;
            break; // Records stay as pending/error — not marked as new errors
        }
        
        if ($http_code === 200 && !empty($response)) {
            $data = json_decode($response, true);
            
            $found_upcs = [];
            if (isset($data['items']) && is_array($data['items'])) {
                foreach ($data['items'] as $product) {
                    $product_upc = $product['upc'] ?? '';
                    $product_ean = $product['ean'] ?? '';
                    
                    $matched_upc = null;
                    if (isset($upc_to_items[$product_upc])) {
                        $matched_upc = $product_upc;
                    } elseif (isset($upc_to_items[$product_ean])) {
                        $matched_upc = $product_ean;
                    } else {
                        $stripped_ean = ltrim($product_ean, '0');
                        foreach ($upc_list as $upc) {
                            if ($upc === $product_upc || $upc === $product_ean || 
                                ltrim($upc, '0') === $stripped_ean || $upc === $stripped_ean) {
                                $matched_upc = $upc;
                                break;
                            }
                        }
                    }
                    
                    if ($matched_upc && isset($upc_to_items[$matched_upc]) && !isset($found_upcs[$matched_upc])) {
                        $extracted = extractUpcitemdbProduct($product);
                        $db_item = $upc_to_items[$matched_upc];
                        $item_response = json_encode($product);
                        
                        $update_stmt->execute([
                            $extracted['product_name'], $extracted['brand'], $extracted['model'],
                            $extracted['asin'], $extracted['country'], $extracted['category'],
                            $extracted['size'], $extracted['color'], $extracted['weight'],
                            $extracted['dimensions'], $extracted['lowest_price'], $extracted['price_currency'],
                            $extracted['image_url'], $extracted['retailer_data'], $item_response,
                            'found', $api_source, $extracted['last_scanned'], $db_item['id']
                        ]);
                        $found++;
                        $found_upcs[$matched_upc] = true;
                    }
                }
            }
            
            foreach ($chunk as $item) {
                if (!isset($found_upcs[$item['upc']])) {
                    $update_stmt->execute([
                        'NOT FOUND', null, null, null, null, null, null, null, null, null,
                        null, null, null, null, json_encode(['batch_query' => true, 'code' => $data['code'] ?? 'OK']),
                        'not_found', $api_source, null, $item['id']
                    ]);
                    $not_found++;
                }
            }
            
            $processed += count($chunk);
            
        } else {
            $error_msg = !empty($curl_error) ? $curl_error : "HTTP $http_code";
            foreach ($chunk as $item) {
                $update_stmt->execute([
                    'API ERROR', null, null, null, null, null, null, null, null, null,
                    null, null, null, null, json_encode(['error' => $error_msg, 'response' => $response]),
                    'error', $api_source, null, $item['id']
                ]);
                $errors++;
            }
            $processed += count($chunk);
        }
        
        // Stop if daily quota is running low
        if ($rate_limit_remaining !== null && $rate_limit_remaining <= 100) {
            $rate_limited = true;
            break;
        }
        
        usleep($config['delay']);
    }
    
} else {
    // ─── SINGLE MODE: Barcode Lookup ───
    foreach ($pending as $item) {
        if ($rate_limited) break;
        
        $upc = $item['upc'];
        $url = $config['url'] . '?barcode=' . urlencode($upc) . '&key=' . $config['key'];
        
        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 10);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
        
        $response = curl_exec($ch);
        $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $curl_error = curl_error($ch);
        curl_close($ch);
        
        if ($http_code === 429) {
            $rate_limited = true;
            break;
        }
        
        if ($http_code === 200 && !empty($response)) {
            $data = json_decode($response, true);
            
            if (isset($data['products']) && is_array($data['products']) && count($data['products']) > 0) {
                $product = $data['products'][0];
                
                $product_name = $product['title'] ?? $product['product_name'] ?? 'Unknown Product';
                $brand = $product['brand'] ?? null;
                $model = $product['model'] ?? $product['mpn'] ?? null;
                $asin = $product['asin'] ?? null;
                $category = $product['category'] ?? null;
                $country = null;
                $size = $product['size'] ?? null;
                $color = $product['color'] ?? null;
                $weight = $product['weight'] ?? null;
                
                $dimensions = null;
                if (isset($product['length']) || isset($product['width']) || isset($product['height'])) {
                    $dim_parts = array_filter([$product['length'] ?? null, $product['width'] ?? null, $product['height'] ?? null]);
                    if (!empty($dim_parts)) {
                        $dimensions = implode(' x ', $dim_parts);
                    }
                } elseif (isset($product['size'])) {
                    $dimensions = $product['size'];
                }
                
                $last_scanned = null;
                if (isset($product['last_update'])) {
                    $last_scanned = date('Y-m-d H:i:s', strtotime($product['last_update']));
                }
                
                $image_url = null;
                if (isset($product['images']) && is_array($product['images']) && count($product['images']) > 0) {
                    $image_url = $product['images'][0];
                }
                
                $retailers = [];
                $lowest_price = null;
                $price_currency = null;
                
                if (isset($product['stores']) && is_array($product['stores'])) {
                    foreach ($product['stores'] as $store) {
                        if (is_string($store)) {
                            $retailers[] = $store;
                        } elseif (isset($store['name'])) {
                            $retailers[] = $store['name'];
                            if (isset($store['price']) && !empty($store['price'])) {
                                $price = floatval($store['price']);
                                if ($lowest_price === null || $price < $lowest_price) {
                                    $lowest_price = $price;
                                    $price_currency = $store['currency'] ?? 'USD';
                                }
                            }
                        }
                    }
                }
                $retailer_data = !empty($retailers) ? implode(', ', $retailers) : 'No retailers listed';
                
                $update_stmt->execute([
                    $product_name, $brand, $model, $asin, $country, $category,
                    $size, $color, $weight, $dimensions, $lowest_price, $price_currency,
                    $image_url, $retailer_data, $response, 'found', $api_source,
                    $last_scanned, $item['id']
                ]);
                $found++;
            } else {
                $update_stmt->execute([
                    'NOT FOUND', null, null, null, null, null, null, null, null, null,
                    null, null, null, null, $response, 'not_found', $api_source,
                    null, $item['id']
                ]);
                $not_found++;
            }
        } else {
            $error_msg = !empty($curl_error) ? $curl_error : "HTTP $http_code";
            $update_stmt->execute([
                'API ERROR', null, null, null, null, null, null, null, null, null,
                null, null, null, null, json_encode(['error' => $error_msg, 'response' => $response]),
                'error', $api_source, null, $item['id']
            ]);
            $errors++;
        }
        
        $processed++;
        usleep($config['delay']);
    }
}

// Return response
if ($is_ajax) {
    ob_end_clean();
    header('Content-Type: application/json');
    $result = [
        'status' => $rate_limited ? 'rate_limited' : 'processing',
        'processed' => $processed,
        'found' => $found,
        'not_found' => $not_found,
        'errors' => $errors,
        'api_source' => $api_source
    ];
    if ($rate_limit_remaining !== null) {
        $result['api_calls_remaining'] = $rate_limit_remaining;
    }
    if ($rate_limited) {
        $result['message'] = 'Rate limit reached. Processing stopped to preserve API quota.';
    }
    echo json_encode($result);
} else {
    $action = $retry_errors ? 'retried' : 'processed';
    header('Location: index.php?' . $action . '=' . $processed . '&source=' . urlencode($api_source));
}
exit;
?>
