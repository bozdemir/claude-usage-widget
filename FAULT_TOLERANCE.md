## Mimari ve Fault Tolerance

Uygulamanın veri toplama akışı, anlık internet kopmalarına ve API kota sınırlarına (Rate Limit - HTTP 429) karşı **Exponential Backoff with Jitter** algoritmasıyla korunuyor.

### Nasıl Çalışıyor?

* **Transient Fault Handling:** Geçici ağ kesintileri veya sunucu taraflı anlık dalgalanmalar (HTTP 5xx) artık uygulamayı doğrudan crash etmiyor.
* **Exponential Delay:** Hata alındığında sistem hemen tekrar çalışmayı denemek yerine, her başarısız denemede bekleme süresini katlayarak ($2^x$ saniye) artırıyor ve sunucuyu yormuyor.
* **Randomized Jitter:** Bekleme sürelerinin üzerine milisaniyelik rastgele gecikmeler ekleniyor. Böylece tüm widget kullanıcılarının aynı anda istek atıp sunucuyu kilitlemesi (**Thundering Herd Problem**) engelleniyor.

## Parametreler

Sistem `claude_usage/cli.py` içinde şu temel sınırlarla çalışıyor:

* **Max Retries:** Uygulama çökmeden önce en fazla 5 kez deniyor.
* **Base Delay:** Üstel artış algoritmasının temel çarpanı 2.0 saniye.(arttırılabilir belki)