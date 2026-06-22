# Каталог литературы для заготовки статьи

Источники соответствуют `Список_литературы.txt` (23 позиции).

## Структура

| Каталог | Содержимое |
|---------|------------|
| `literature/pdf/` | Полные тексты (PDF), где удалось скачать |
| `literature/segments/` | Выдержки для цитирования (abstract, ключевые абзацы) |
| `literature/download_literature.sh` | Скрипт повторной загрузки PDF |

---

## Сводная таблица

| № | Источник | PDF | Сегмент | Примечание |
|---|----------|-----|---------|------------|
| 1 | ORB-SLAM3 (Campos et al., TRO 2021) | `pdf/01_ORB-SLAM3.pdf` | `segments/01_ORB-SLAM3_abstract_intro.txt` | arXiv preprint |
| 2 | VINS-Mono (Qin et al., TRO 2018) | `pdf/02_VINS-Mono.pdf` | `segments/02_VINS-Mono_abstract_intro.txt` | arXiv |
| 3 | OKVIS (Leutenegger et al., IJRR 2015) | `pdf/03_OKVIS.pdf` | `segments/03_OKVIS_abstract_intro.txt` | авторский PDF |
| 4 | Preintegration (Forster et al., TRO 2017) | `pdf/04_Preintegration.pdf` | `segments/04_Preintegration_abstract_intro.txt` | arXiv |
| 5 | ORB-SLAM2 (Mur-Artal, TRO 2017) | `pdf/05_ORB-SLAM2.pdf` | `segments/05_ORB-SLAM2_abstract_intro.txt` | arXiv |
| 6 | Huang et al., observability (TRO/IJRR 2010) | `pdf/06_Huang2010_Observability.pdf` | `segments/06_Huang_observability_key.txt` | MIT mirror |
| 7 | Li & Mourikis, MSCKF 2.0 (IJRR 2013) | `pdf/07_Li2013_MSCKF.pdf` | `segments/07_Li_MSCKF_consistency.txt` | Semantic Scholar (слайды/конспект; для полного текста — SAGE) |
| 8 | OpenVINS (Geneva et al., ICRA 2020) | `pdf/08_OpenVINS.pdf` | `segments/08_OpenVINS_key.txt` | авторский PDF |
| 9 | Sun et al., RSS 2017 | `pdf/09_Sun2017_substitute_VO_PartII.pdf` | `segments/09_outlier_RANSAC_key.txt` | **см. `09_Sun2017_NOTE.txt`** — оригинал не найден, заменитель |
| 10 | SuperPoint (DeTone et al., CVPRW 2018) | `pdf/10_SuperPoint.pdf` | `segments/10_SuperPoint_abstract.txt` | arXiv |
| 11 | SuperGlue (Sarlin et al., CVPR 2020) | `pdf/11_SuperGlue.pdf` | `segments/11_SuperGlue_abstract.txt` | arXiv |
| 12 | Brachmann & Rother, Less is More (CVPR 2018) | `pdf/12_Brachmann_LessMore.pdf` | `segments/12_Brachmann_key.txt` | arXiv; также `12b_Brachmann_DSAC2017.pdf` |
| 13 | DROID-SLAM (Teed & Deng, NeurIPS 2021) | `pdf/13_DROID-SLAM.pdf` | `segments/13_DROID-SLAM_abstract.txt` | arXiv |
| 14 | Eigen et al., depth (NIPS 2014) | `pdf/14_Eigen_Depth.pdf` | `segments/14_Eigen_depth_key.txt` | arXiv |
| 15 | DPT (Ranftl et al., ICCV 2021) | `pdf/15_DPT.pdf` | `segments/15_DPT_key.txt` | arXiv |
| 16 | AdaBins (Bhat et al., CVPR 2021) | `pdf/16_AdaBins.pdf` | `segments/16_AdaBins_key.txt` | arXiv |
| 17 | Song et al., Sensors 2024 | — | `segments/17_Song2024_abstract_intro.txt` | MDPI open access, PDF 403 при wget |
| 18 | Yang et al., Measurement 2026 | — | `segments/18_Yang2026_bibliography.txt` | paywall (2026) |
| 19 | Kim et al., RA-L 2021 | — | `segments/19_Kim2021_bibliography.txt` | IEEE paywall |
| 20 | Zaffar et al., VPR-Bench (IJCV 2021)* | `pdf/20_Zaffar_VPR-Bench.pdf` | `segments/20_Zaffar_abstract.txt` | Springer OA; в списке указан IEEE TITS — уточнить запись |
| 21 | KITTI (Geiger et al., CVPR 2012) | `pdf/21_KITTI.pdf` | `segments/21_KITTI_abstract.txt` | cvlibs.net |
| 22 | EuRoC (Burri et al., IJRR 2016) | — | `segments/22_EuRoC_abstract.txt` | SAGE; abstract + dataset page |
| 23 | TUM-VI (Schubert et al., IJRR 2021) | `pdf/23_TUM-VI.pdf` | `segments/23_TUM-VI_abstract.txt` | arXiv |

\* Позиция 20 в `Список_литературы.txt` указывает IEEE TITS 2021; найденная открытая версия — IJCV 2021 (тот же авторский состав, расширенная статья VPR-Bench).

---

## Статистика загрузки

- **PDF скачано:** 19 файлов (~89 MB)
- **Только сегменты/метаданные:** №17, 18, 19, 22
- **Требует проверки библиографии:** №9, №20

---

## Ключевые источники для нашей статьи (адаптивное доверие / OpenVINS)

| Тема | Источники |
|------|-----------|
| Базовая платформа | #8 OpenVINS, #7 MSCKF 2.0, #6 observability |
| Сравнение VIO | #2 VINS-Mono, #3 OKVIS, #1 ORB-SLAM3 |
| IMU | #4 preintegration |
| Outliers / robustness | #9 (заменитель), #13 DROID-SLAM |
| Uncertainty / depth | #17 Song, #14–16 depth networks |
| Датасеты | #21 KITTI, #22 EuRoC, #23 TUM-VI |
| Деградация / погода | #19 Kim, #20 Zaffar (motion blur) |

---

## Повторная загрузка

```bash
bash literature/download_literature.sh
```

Извлечение сегментов из PDF (после обновления pdf/):

```bash
python3 - <<'PY'
# см. историю сессии: скрипт pdftotext + regex Abstract/Introduction
PY
```

---

## Действия перед финальной статьёй

1. Получить PDF #17 (MDPI), #19 (IEEE), #22 (SAGE) через институциональный доступ.
2. Уточнить или исправить ссылку #9 (Sun RSS 2017).
3. Сверить запись #20 (IJCV vs IEEE TITS).
4. Для #7 заменить PDF на полную версию IJRR при наличии доступа.
