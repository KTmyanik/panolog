# TODO

## İlk sürüm ilerlemesi

- [x] Aşama 1: Çekirdek (izleme + sınıflandırma + DB + popup + tray + ayarlar)
- [x] Aşama 2: Dosyalar kategorisi
- [x] Aşama 3: Hassas veri maskeleme
- [x] Aşama 4: Şablonlar
- [x] Aşama 5: OCR
- [x] Aşama 6: PyInstaller paketleme, README'nin tamamlanması, şifreleme değerlendirmesi
- [x] OCR iyileştirmesi: yerel OCR modeli (kod/numara) + Windows Türkçe motoru, otomatik birleştirme
- [x] Görsellerde büyük önizleme (imleç / Boşluk) ve düzenleyici: kapatma, bulanıklaştırma, kırpma
      (aşağıdaki "Hızlı görsel düzenleme" maddesinin ok/kutu çizme kısmı yapılmadı)
- [x] Metin/link/şablon önizlemesi (Boşluk), "Sonraki kopyayı kaydetme" ve 5 dakika duraklatma,
      görseli PNG dosyası olarak kaydetme (Ctrl+Shift+S)
- [x] Seçilebilir temalar: Klasik, Aurora cam, Kâğıt masa, Sert çizgi (Ayarlar > Görünüm)
- [x] Görsel şablonlar: şablon penceresinde çizim alanı (ör. imza), dosyadan ya da geçmişteki
      görselden şablon

## Yapılacaklar listesi (ilk sürüme dahil DEĞİL, sonraki aşamalar)
### Aşama 2: Günlük kullanım hızlandırıcıları
- [ ] Kod/SQL kategorisi: SQL, JSON, XML ve kod parçalarını algıla, sözdizimi renklendirmesiyle göster
- [ ] Metin dönüştürme menüsü: büyük/küçük harf (Türkçe İ/ı kurallarına uygun), boşluk temizleme, satırları birleştirme, JSON güzelleştirme, Türkçe karakter düzeltme
- [ ] Çoklu seçim ve birleştirme: birkaç öğeyi seçip ayraçla tek seferde yapıştırma
- [ ] Sıralı yapıştırma modu: her Ctrl+V'de listedeki bir sonraki öğeyi yapıştır
- [ ] Akıllı link işleme: sayfa başlığı ve favicon gösterimi, takip parametrelerini (utm_ vb.) temizleyerek yapıştırma
- [ ] Hızlı görsel düzenleme: kırpma, ok/kutu çizme, hassas alanı bulanıklaştırma, yapıştırmadan önce
### Aşama 3: Düzen ve kontrol
- [ ] Uygulamaya göre kurallar (örn. Excel'den gelenleri kaydetme, Teams'ten gelenleri etiketle)
- [ ] Etiketler ve klasörler: sabitlenen öğeleri gruplama
- [ ] Dışa aktarma/yedekleme: seçili öğeleri veya tüm geçmişi JSON/Markdown olarak aktarma
- [ ] Windows 11 görünümü: koyu/açık tema, Mica efekti, yuvarlak köşeler
- [ ] Kullanım istatistikleri: günlük kopyalama sayısı, en çok kullanılan uygulamalar
### Aşama 4: İleri seviye (varsayılan kapalı, gizlilik değerlendirmesi gerekir)
- [ ] Yerel yapay zeka entegrasyonu: seçili metni özetle/çevir/düzelt (dış API kullanılacaksa açık kullanıcı onayı ve hassas veri filtresi şart)
- [ ] Cihazlar arası eşitleme (telefon ↔ PC): uçtan uca şifreleme gerektirir, ayrı bir tasarım dokümanıyla ele alınsın
- [ ] Veritabanı şifrelemesinin zorunlu hale getirilmesi (ilk sürümde değerlendirme sonucuna göre)
