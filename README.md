# Panolog

Windows 11 için kategorili clipboard geçmiş yöneticisi. Kopyaladığınız görselleri, metinleri,
linkleri ve dosyaları ayrı sekmelerde saklar; global kısayolla açılan pencereden geri
yapıştırırsınız.

> Durum: ilk sürümün tüm aşamaları tamamlandı. Sonraki aşamalar için planlanan, henüz
> yapılmamış işler `TODO.md` dosyasındadır.

## Kurulum (geliştirme)

Python 3.11+ gerekir.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Çalıştırma

```powershell
.\.venv\Scripts\pythonw.exe -m panolog
```

Uygulama sistem tepsisine yerleşir. Testler: `.\.venv\Scripts\python.exe -m pytest`

## Tek dosyalık .exe üretme

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
```

```powershell
.\.venv\Scripts\pyinstaller.exe packaging\panolog.spec --noconfirm
```

Çıktı `dist\Panolog.exe` dosyasıdır (yaklaşık 85 MB; yerel OCR modeli dahil, Python kurulu olmayan makinede de
çalışır). Paketin sağlam olduğunu, çalışan kopyaya ve verilere dokunmadan doğrulamak için:

```powershell
.\dist\Panolog.exe --self-test rapor.txt; Get-Content rapor.txt -Encoding utf8
```

Rapor dört bileşeni (depolama, PNG, arayüz, OCR) sınar; son satır `SONUÇ: başarılı` olmalıdır.
OCR satırı yerel modelin ve Windows motorunun paketin içinden çalıştığını, ayrıca Windows'ta
yüklü OCR dillerini gösterir.

Bilinmesi gerekenler:

- **Kurulum yoktur.** `.exe`'yi kalıcı bir klasöre (ör. `%LOCALAPPDATA%\Programs\Panolog`)
  koyup çalıştırın. "Windows ile başlangıçta çalıştır" ayarı `.exe`'nin o anki yolunu kaydeder;
  dosyayı taşırsanız ayarı kapatıp yeniden açın.
- **Veriler `.exe` ile birlikte taşınmaz;** `%LOCALAPPDATA%\Panolog\` altında kalır. Kaynaktan
  çalıştırılan sürümle aynı veriyi kullanır, ikisi aynı anda çalışamaz.
- **Tek dosya her açılışta kendini geçici klasöre açar** (`%TEMP%\_MEI…`); açılış yaklaşık
  2-3 saniye sürer. Kurumsal makinelerde güvenlik yazılımı `%TEMP%`'ten çalıştırmayı engelliyorsa tarifteki
  `EXE(...)` bölümünü klasör çıktısına (`COLLECT`) çevirmek gerekir.
- **İmzasızdır.** SmartScreen ilk çalıştırmada uyarı gösterebilir, antivirüsler PyInstaller ile
  paketlenmiş imzasız dosyalarda yanlış alarm verebilir. Kurum içinde dağıtılacaksa kod imzalama
  sertifikasıyla imzalanmalıdır. Bu yüzden UPX sıkıştırması kapalıdır.
- Paket küçük kalsın diye kullanılmayan Qt parçaları (çeviriler, yazılımsal OpenGL, ağ modülü)
  tarifte ayıklanır; uygulama zaten ağ kullanmaz.

## Kullanım

| Tuş | İşlev |
| --- | --- |
| `Ctrl+Shift+V` | Pencereyi aç/kapat (ayarlardan değiştirilebilir) |
| `Tab` / `Shift+Tab`, `←` `→` | Sekme değiştir (oklar arama kutusu boşken) |
| `↑` `↓` | Listede gezin |
| `Enter` | Seçili öğeyi yapıştır |
| `Shift+Enter` | Düz metin olarak yapıştır (biçimlendirme atılır; dosyalarda yollar metin olarak yapışır) |
| `1`–`9` | İlk 9 öğeyi doğrudan yapıştır (arama doluyken `Alt+1`–`9`) |
| yazmaya başla | Ara (büyük/küçük harf ve İ/ı duyarsız) |
| `Ctrl+P` | Sabitle / sabitlemeyi kaldır |
| `Ctrl+S` | Seçili öğeyi şablon olarak kaydet |
| `Ctrl+O` | Seçili görseldeki metni çıkar (OCR): Metinler'e ekler ve clipboard'a kopyalar |
| `Ctrl+N` / `Ctrl+E` | Şablonlar sekmesinde: yeni şablon / seçili şablonu düzenle |
| `Delete` | Seçili öğeyi sil |
| `Esc` | Kapat |

Tray menüsü: Duraklat/Devam et, Geçmişi temizle (sabitlenenler kalır), Şablonlar, Ayarlar, Çıkış.

## Şablonlar

Kalıcı metin parçalarıdır: ad, isteğe bağlı kısa kod (ör. `;imza`), içerik ve isteğe bağlı
etiket. Geçmiş limitinden, otomatik temizlikten ve "Tüm geçmişi sil"den etkilenmezler.

- **Kullanım:** Popup'ta Şablonlar sekmesinden seçilir. Arama ad, kısa kod, etiket ve içerikte
  yapılır; kısa kodu aramayla birebir eşleşen şablon en üste gelir (`;imza` yazıp `Enter`).
- **Kısa kod bir arama anahtarıdır,** yazarken otomatik genişlemez. Her yerde `;imza` yazınca
  metnin kendiliğinden değişmesi tüm tuş vuruşlarını izleyen bir klavye kancası gerektirir;
  bu uygulama bilinçli olarak kanca kurmaz (bkz. Tasarım kararları).
- **Değişkenler:** `{tarih}` (GG.AA.YYYY), `{saat}` (SS:DD), `{pano}` (şablon seçildiği anda
  clipboard'da olan metin). Bilinmeyen `{…}` ifadeleri olduğu gibi kalır.
- **Geçmişten şablon:** Herhangi bir metin, link veya dosya öğesi seçiliyken `Ctrl+S`
  (dosyalarda yollar metin olarak alınır; görseller şablon olamaz).
- **Silme:** Şablonlar sekmesinde `Delete` iki kez basılınca siler.
- **Yönetim ve JSON:** Tray > Şablonlar penceresinden ekleme, düzenleme, silme, içe ve dışa
  aktarma. İçe aktarırken kısa kodu zaten kayıtlı olan şablon güncellenir, adı ve içeriği
  aynı olan atlanır.
- Yapıştırılan (değişkenleri açılmış) şablon metni geçmişe ayrıca kaydedilmez.

## Görsellerden metin okuma (OCR)

İki yerel motor birlikte çalışır; görsel hiçbir yere gönderilmez ve seçim yapmanız gerekmez.

- **Yerel OCR modeli** (PP-OCRv6, ONNX Runtime ile): temel okuma buradan gelir. Kod, numara
  ve noktalamada güçlüdür (`column1`, `PersonID`, `);`, IBAN/kart numaraları).
- **Windows'un Türkçe OCR motoru** (`Windows.Media.Ocr`): Türkçe satırlarda harf düzeltmeleri
  (ı/İ, ş, ğ, ç, ö, ü) buradan alınır; model bu ayrımda zayıftır ("çikiş yapin").

Birleştirme kuralı: temel her zaman modelin okumasıdır. Windows'un yazımı yalnızca Türkçe
olduğu anlaşılan satırlarda (satırda ç, ğ, ö, ş, ü geçiyorsa ya da belgenin çoğu öyleyse ve
satır kod değilse), yalnızca iki motorun aynı sözcüğü okuduğu yerlerde ve yalnızca Türkçe
harf farkları için alınır. Kod satırlarına Windows hiç karışmaz (tek başına `PRİMARY`,
`c01umn` gibi hatalar üretir).

Ölçüm (üretilmiş ekran görüntüleri; 3 yazı tipi, 9-14 punto, açık/koyu tema; birebir doğru
okunan satır sayısı):

| Belge | Satır | Yalnız model | Yalnız Windows (Türkçe) | Birleşik |
| --- | --- | --- | --- | --- |
| Kod / İngilizce | 108 | 104 | 14 | 104 |
| Türkçe düz metin | 108 | 55 | 70 | 87 |
| Karışık (Türkçe içeren SQL vb.) | 108 | 80 | 33 | 93 |

Kullanım:

- **Metne çevir:** Görseller sekmesinde bir görsel seçiliyken `Ctrl+O`. Okunan metin yeni bir
  öğe olarak Metinler'e (tek bir URL ise Linkler'e) eklenir, clipboard'a kopyalanır ve pencere
  o öğeye geçer; `Enter` ile yapıştırılır. Kaynak uygulama olarak `OCR` görünür.
- **Görsel aranabilir olur:** Okunan metin görselle birlikte saklanır; Görseller sekmesinde
  arama bu metinde yapılır ve ilk satırı küçük resmin altında görünür. Aynı görselde ikinci
  `Ctrl+O` motoru yeniden çalıştırmaz, saklanan metni kullanır.
- **Otomatik OCR** (Ayarlar > OCR, varsayılan **kapalı**): Açılınca her yeni görsel ve
  geçmişteki okunmamış görseller arka planda sırayla okunur. Bu modda Metinler'e öğe
  eklenmez; yalnızca görseller aranabilir hale gelir.
- **Komut satırından deneme:** Geçmişe ve clipboard'a dokunmadan tek bir görseli okutmak için
  `Panolog.exe --ocr görsel.png çıktı.txt` (kaynaktan: `python -m panolog --ocr ...`).

Süre ve bellek (20 çekirdekli geliştirme makinesinde ölçüldü; zayıf makinede uzar):

- Okuma: küçük bir ekran görüntüsünde yaklaşık 0,6 sn (model) + Windows motoru; ilk okumada
  modelin yüklenmesi yaklaşık 1 sn ekler. Tam ekran (1920×1080) görselde yaklaşık 1 sn.
- Model yalnızca ilk OCR'da yüklenir ve yüklüyken yaklaşık 570 MB bellek kullanır; 2 dakika
  OCR yapılmazsa bellekten bırakılır (ölçülen: 108 MB'a iner). Çekirdeklerin en çok yarısı,
  en çok 4'ü kullanılır.

Türkçe OCR dil paketi:

- Yüklü değilse kod ve numaralar yine doğru okunur, ama Türkçe metinde ı/i ve İ/I karışabilir;
  ilk kullanımda ve Ayarlar > OCR'da uyarı gösterilir. Yüklü dilleri görmek için (yönetici
  gerekmez, Windows PowerShell 5.1):

  ```powershell
  [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null; [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | Select-Object LanguageTag, DisplayName
  ```

- Kurulum: Ayarlar > Zaman ve dil > Dil ve bölge > Dil ekle > Türkçe, ya da yönetici
  PowerShell'de:

  ```powershell
  Add-WindowsCapability -Online -Name "Language.OCR~~~tr-TR~0.0.1.0"
  ```

Bilinen sınırlar (sonuç özellikle kod ve numaralarda kontrol edilmeli):

- Yalnızca nokta içeren satırlar (`...`) her zaman okunamaz; bazen eksik (`..`) çıkar ya da
  atlanır. Diğer noktalama satırları (`);`, `}`) çoğunlukla okunur.
- Türkçede cümle başındaki `İ` bazen küçük `i` okunur; kod içindeki Türkçe sözcüklerde
  (ör. `'İstanbul'`) düzeltme yapılmaz, çünkü kod satırlarına Windows karıştırılmaz.
- Satır başı girintileri ve hizalama korunmaz. Metin yatay kabul edilir; eğik ya da döndürülmüş
  metin (fotoğraf) için tasarlanmadı. El yazısı desteklenmez.
- Hassas veri ayarı OCR metnine de uygulanır (ör. "Hiç kaydetme" modunda metin clipboard'a
  kopyalanır ama geçmişe eklenmez). Görsel üzerindeki metin için maskeleme yapılmaz.

Modelin kaynağı ve tasarım kararı:

- Model dosyaları `src/panolog/ocr/models/` altındadır: PaddleOCR'ın PP-OCRv6 "small"
  metin bulucu ve tanıyıcı modellerinin RapidOCR projesince ONNX'e çevrilmiş halleri
  (toplam 31 MB, Apache-2.0; ayrıntı ve SHA-256 değerleri aynı klasördeki
  `MODEL_LICENSES.md` dosyasında). Dosyalar RapidOCR 3.10.0 paketinden alınmış, SHA-256
  değerleri o paketin yayımladığı değerlerle karşılaştırılarak doğrulanmıştır.
- RapidOCR paketinin kendisi **kullanılmaz**; modeller doğrudan ONNX Runtime ile çalıştırılır,
  görüntü işleme Qt ve NumPy ile yapılır. Gerekçe: paket OpenCV, Shapely gibi büyük
  bağımlılıklar getiriyor (`.exe` 146 MB oluyordu, böyle 85 MB) ve eksik modeli ağdan indiren
  kod içeriyor. Bu uygulamada ağ kodu yoktur.
- Kendi yazılan adımlar: metin kutularının çıkarılması (yatay metin varsayımıyla), bulucunun
  ayrı kutu verdiği satır sonu noktalamasının satırla birleştirilmesi ve bulucunun hiç
  görmediği küçük parçaların (ör. `...`) ayrıca okutulması.
- `onnxruntime` ve `numpy` kurulu değilse ya da model dosyaları yoksa uygulama yalnızca
  Windows OCR ile çalışmaya devam eder.

## Tasarım kararları

### Global kısayol: `keyboard`/`pynput` yerine `RegisterHotKey`

`keyboard` ve `pynput` global kısayolu düşük seviyeli klavye kancası (`WH_KEYBOARD_LL`) ile
uygular; yani süreç sistemdeki **her** tuş vuruşunu görür. Bu, özellikle kurumsal/bankacılık
ortamlarında güvenlik yazılımlarının keylogger olarak işaretleyebileceği bir davranıştır;
`keyboard` paketi ayrıca artık bakım görmüyor. Bunun yerine Win32 `RegisterHotKey` kullanılır:
uygulama yalnızca kayıtlı kombinasyon basıldığında haberdar olur, başka hiçbir tuşu görmez ve
ek bağımlılık gerekmez. Eksisi: kombinasyon başka bir uygulamada kayıtlıysa alınamaz; bu
durumda tray bildirimiyle uyarılırsınız ve ayarlardan başka bir kısayol seçebilirsiniz.

### Clipboard izleme

`AddClipboardFormatListener` ile `WM_CLIPBOARDUPDATE` dinlenir (yoklama yok). Şu kopyalar
kaydedilmez: `ExcludeClipboardContentFromMonitorProcessing` veya
`CanIncludeInClipboardHistory = 0` işareti taşıyanlar ve ayarlardaki hariç tutulan
uygulamalardan (varsayılan: KeePass, KeePassXC, Bitwarden, 1Password) gelenler.

### Sınıflandırma

Öncelik: dosya > metin/link > görsel. Metnin tamamı tek bir URL ise yalnızca Linkler'e düşer.
Metin ve görsel birlikte geldiğinde (ör. Excel hücresi) metin sayılır.

### Dosyalar

Explorer'da kopyalanan dosya/klasörlerin içeriği değil **yolu** saklanır; birden çok dosyalık
bir seçim tek öğedir. Yapıştırırken clipboard'a dosya referansı (`CF_HDROP`) yazılır, yani
Explorer'a yapıştırınca orijinal dosya kopyalanır. Dosya sonradan silinmiş veya taşınmışsa
o yol atlanır; hiçbiri kalmamışsa bildirim gösterilir. Boyut kopyalama anında kaydedilir.
Ağ sürücülerindeki dosyalar için genel ikon kullanılır; böylece erişilemeyen bir paylaşım
pencereyi dondurmaz.

## Hassas veri

**Varsayılan olarak kapalıdır:** IBAN, kart numarası, TCKN gibi değerler de diğer her şey gibi
normal ve süresiz kaydedilir (test/UAT çalışmalarında bu değerler sık kopyalanıp tekrar
kullanıldığı için). Koruma istenirse Ayarlar > Gizlilik'ten bir davranış seçilir; o zaman
kopyalanan her metin ve link kaydedilmeden önce şu kalıplar için taranır:

| Tür | Algılama |
| --- | --- |
| IBAN | Ülke kodu + ülkeye özgü uzunluk + mod-97 (TR dahil ~60 ülke); boşluklu/bitişik yazım |
| Kredi kartı | 13-19 hane + Luhn; boşluk veya tire ile gruplanmış olabilir |
| TC kimlik no | 11 hane, 0 ile başlamaz, 10. ve 11. hane resmi algoritmayla doğrulanır |
| Parola/anahtar satırı | `password`, `passwd`, `parola`, `şifre`/`sifre`, `token`, `api_key`/`api-key`/`apikey` geçen satırlar |
| E-posta, telefon | Varsayılan **kapalı**; Ayarlar > Gizlilik'ten açılır |

Seçilebilecek davranışlar (Ayarlar > Gizlilik):

1. **Normal kaydet** (varsayılan): tarama yapılmaz, özel işlem yok.
2. **Kaydet, listede maskeli göster** (süresiz; ör. `TR33 **** 1326`, `**** **** **** 1111`,
   `password: ********`). Yapıştırınca asıl değer yapışır; maskelenen kısım aramada da çıkmaz.
3. **Kaydet, 60 saniye sonra otomatik sil.** Listede geri sayım görünür. Öğeyi sabitlemek
   süreyi iptal eder; aynı içeriği yeniden kopyalamak sayacı baştan başlatır.
4. **Hiç kaydetme**

Bilinmesi gerekenler:

- Algılama yalnızca metin ve linklerde çalışır; görsellerin ve dosyaların içeriği taranmaz
  (görselden OCR ile çıkarılıp Metinler'e eklenen metin taranır).
- Luhn rastgele 13-19 haneli sayıların yaklaşık %10'unda da tutar; böyle bir sayı (ör. bir
  referans numarası) kart sanılıp hassas işaretlenebilir. Tercih bilinçli: kaçırmaktansa
  fazla korumak.
- Bu uygulama yalnızca kendi geçmişini yönetir. Değer sistem clipboard'ında ve (açıksa)
  Windows'un kendi `Win+V` geçmişinde kalmaya devam eder.

## Gizlilik

Tüm veri `%LOCALAPPDATA%\Panolog\` altındadır (`panolog.db` ve `images\`). Uygulama ağ
bağlantısı kurmaz, telemetri yoktur. SQLite `secure_delete` açıktır; silinen içerik dosyada
kalmaz. Ayarlar > Gizlilik > "Tüm geçmişi sil" sabitlenenler dahil tüm geçmişi siler
(şablonlar kalır).

Uygulamanın eski adı Clipboarder'dı. Eski sürümden kalan veriler
(`%LOCALAPPDATA%\Clipboarder\`) ve başlangıç kaydı, Panolog ilk açıldığında otomatik olarak
yeni ada taşınır; eski sürüm o sırada çalışıyorsa önce kapatmanız istenir.

### Veritabanı şifrelemesi (SQLCipher) değerlendirmesi

İlk sürümde veritabanı **şifrelenmez**. Gerekçesiyle birlikte değerlendirme:

Şifrelemenin koruduğu durumlar:

- Disk şifrelenmemiş bir makinenin çalınması veya diskinin sökülüp okunması.
- Veri klasörünün bir yedeğe, senkronize klasöre veya destek paketine kazara girmesi.
- Aynı makinede başka bir Windows hesabıyla (yönetici) dosyalara bakılması.

Korumadığı durumlar:

- Kullanıcının kendi oturumunda çalışan kötü amaçlı yazılım. Anahtar ister Windows DPAPI ile
  saklansın ister bellekte dursun, aynı kullanıcı olarak çalışan süreç ona da ulaşır; ayrıca
  clipboard'un kendisini zaten doğrudan okuyabilir.
- Windows'un kendi `Win+V` geçmişi ve kopyalanan değerin o anda clipboard'da durması.

Maliyeti:

- Python'un yerleşik `sqlite3` modülü SQLCipher'ı desteklemez. Ayrı bir derlenmiş paket gerekir
  (`sqlcipher3` veya `pysqlcipher3`); bunların her Python sürümü için hazır Windows paketi
  olmayabiliyor, bu da derleme ortamı ve `.exe` paketlemesinde ek bakım demek.
- Görseller veritabanında değil diskte PNG olarak durur; SQLCipher onları şifrelemez. Tutarlı
  bir koruma için görsellerin de ayrıca şifrelenmesi gerekir (her önizlemede çözme maliyeti).
- Anahtar yönetimi: her açılışta parola sormak arka planda sessizce çalışan bir araç için
  kullanışsız; DPAPI ile saklanan anahtar ise yukarıdaki sınırlı korumayı verir ve Windows
  profili bozulursa/sıfırlanırsa geçmiş geri getirilemez.
- Mevcut şifresiz veritabanından geçiş (göç) adımı ve her sorguda küçük bir yavaşlama.

Sonuç ve öneri:

- Bu uygulamanın tehdit modelinde asıl risk **diskin fiziksel olarak ele geçmesidir** ve bunu
  BitLocker (kurumsal makinelerde genelde zaten zorunlu) hem veritabanı hem görseller için,
  ek kod olmadan çözer. Tam disk şifrelemesi olan makinede SQLCipher'ın ek katkısı küçüktür.
- Uygulama zaten veriyi kullanıcıya özel `%LOCALAPPDATA%` altında tutar, `secure_delete` ile
  silinenleri dosyadan temizler, otomatik temizlik ve isteğe bağlı hassas veri modları sunar.
- Şifreleme zorunlu hale getirilecekse (bkz. `TODO.md`, Aşama 4) önerilen yol: SQLCipher +
  DPAPI ile saklanan rastgele anahtar, görseller için aynı anahtarla dosya şifrelemesi ve
  bunun ayrı bir tasarım notuyla ele alınması. Daha hafif bir ara çözüm, veri klasörünü
  Windows EFS ile şifrelemektir (`cipher /e`); kod değişikliği gerektirmez.
