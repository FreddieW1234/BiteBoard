# Tests an API key exactly the way a customer's nightly job uses the feed.
# Run:  powershell -ExecutionPolicy Bypass -File ".\test-feed-key.ps1"
# Paste the key (from the Copy button) when asked - it is not shown on screen.

$base = "https://api.bitepromotions.co.uk"
$secure = Read-Host "Paste the API key" -AsSecureString
$key = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim()
$h = @{ Authorization = "Bearer $key" }
$pass = 0; $fail = 0
function Check($ok, $what) {
    if ($ok) { $script:pass++; Write-Host "  PASS  $what" -ForegroundColor Green }
    else { $script:fail++; Write-Host "  FAIL  $what" -ForegroundColor Red }
}

Write-Host "`n1. Ping"
try {
    $ping = Invoke-RestMethod "$base/api/v1/ping" -Headers $h -TimeoutSec 60
    Check ($ping.ok -eq $true) "key accepted"
    Check ($ping.price_list -in @("trade", "end-customer")) "price list: $($ping.price_list)"
    Check ([bool]$ping.generated_at) "catalogue built: $($ping.generated_at)"
} catch { Check $false "ping failed: $($_.Exception.Message)" }

Write-Host "`n2. Download the feed (compressed, as customers should)"
try {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-WebRequest "$base/api/v1/feed" -Headers ($h + @{ "Accept-Encoding" = "gzip" }) -UseBasicParsing -TimeoutSec 120
    $sw.Stop()
    Check ($r.StatusCode -eq 200) "status 200 in $([math]::Round($sw.Elapsed.TotalSeconds,1))s"
    $etag = $r.Headers["ETag"]
    Check ([bool]$etag) "ETag sent"
    $feed = $r.Content | ConvertFrom-Json
    Check ($feed.product_count -gt 0 -and $feed.product_count -eq @($feed.products).Count) "$($feed.product_count) products"
    Check ($feed.currency -eq "GBP" -and $feed.prices_include_vat -eq $false) "GBP, prices exclude VAT"
    Check ($feed.price_list -eq $null) "no other price list exposed"
    $noPrice = @($feed.products | Where-Object { -not $_.price_breaks -or @($_.price_breaks | Where-Object { $_.price -le 0 }).Count })
    Check ($noPrice.Count -eq 0) "every product has prices above zero"
    $ids = @($feed.products.id); Check (($ids | Sort-Object -Unique).Count -eq $ids.Count) "product ids unique"
    $p = $feed.products | Where-Object { $_.artwork_templates_url } | Select-Object -First 1
    Check ([bool]$p) "artwork template links present"
    $fields = "id","handle","sku","title","url","price_breaks","description","categories","images","moq","lead_times","product_size","allergens","dietary","ingredients","artwork_guidelines_url"
    $missing = $fields | Where-Object { -not ($feed.products[0].PSObject.Properties.Name -contains $_) }
    Check ($missing.Count -eq 0) "all main fields present$(if ($missing) { ': missing ' + ($missing -join ', ') })"
    $raw = ($r.RawContent -split "`r`n`r`n", 2)[1]
    Check ($raw -notmatch "pricejson") "no internal price data in the response"

    Write-Host "`n3. Repeat pull with the ETag (what a nightly job does)"
    try {
        Invoke-WebRequest "$base/api/v1/feed" -Headers ($h + @{ "If-None-Match" = $etag }) -UseBasicParsing -TimeoutSec 60 | Out-Null
        Check $false "expected 304 Not Modified"
    } catch { Check ($_.Exception.Response.StatusCode.value__ -eq 304) "304 Not Modified (nothing re-downloaded)" }

    Write-Host "`nExample product:"
    $feed.products[0] | Select-Object sku, title, @{n="from_price"; e={ $_.price_breaks[-1].price }}, product_size, shelf_life, url | Format-List
} catch { Check $false "feed failed: $($_.Exception.Message)" }

Write-Host ("`n{0} passed, {1} failed`n" -f $pass, $fail) -ForegroundColor $(if ($fail) { "Red" } else { "Green" })
$key = $null
