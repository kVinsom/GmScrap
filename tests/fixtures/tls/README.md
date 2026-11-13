These self-signed certificate and private key files are public test fixtures.
They are used only by loopback HTTPS servers; never use them for deployment.

The certificate covers `cafe.example` and `xn--80aaf4a.example` (an internationalized test hostname).
Tests explicitly trust this certificate for positive cases and retain real TLS
certificate and hostname verification. No OpenSSL executable is needed to run
the tests. Keep these fixtures in source distributions as well as the checkout.
