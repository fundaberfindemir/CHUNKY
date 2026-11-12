# Ek kök sertifikalar (isteğe bağlı)

Bazı antivirüs programları (ör. Norton, Avast, Kaspersky) veya kurumsal ağlar HTTPS
trafiğini kendi sertifikalarıyla denetler. Bu durumda Docker derlemesi sırasında
`pip` şu hatayı verir:

```
SSL: CERTIFICATE_VERIFY_FAILED ... unable to get local issuer certificate
```

Çözüm: Denetleyen yazılımın **kök sertifikasını** (yalnızca herkese açık kısmı,
`.crt` / PEM biçiminde) bu klasöre koyun. Dockerfile buradaki tüm `.crt` dosyalarını
konteynerin güvenilir sertifikalarına ekler.

- Bu klasördeki `.crt` dosyaları makineye özeldir ve `.gitignore` ile git'e **girmez**.
- Klasör boşsa Docker derlemesi normal şekilde çalışır.

Windows'ta sertifikanın kime ait olduğunu görmek için (PowerShell):

```powershell
$t = [Net.Sockets.TcpClient]::new('pypi.org', 443)
$s = [Net.Security.SslStream]::new($t.GetStream(), $false, { $true })
$s.AuthenticateAsClient('pypi.org')
$c = [Security.Cryptography.X509Certificates.X509Chain]::new()
[void]$c.Build($s.RemoteCertificate); $c.ChainElements.Certificate | Select Subject, Thumbprint
```
