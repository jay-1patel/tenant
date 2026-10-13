$body = '{"user_name":"Test!ing","password":"Leeway@2026","from_date":"2026-10-12 00:00:00","to_date":"2026-10-12 23:59:59"}'
try {
  $r = Invoke-RestMethod -Uri 'https://api.send2.digital/devdesk/send-report' -Method Post -ContentType 'application/json' -Body $body
  $r | ConvertTo-Json -Compress -Depth 5
} catch {
  "ERR: $($_.Exception.Message)"
}
