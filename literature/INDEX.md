# Каталог литературы

Префикс файла = номер ссылки [1]–[27] в `Статья_v6.txt` / `Список_литературы.txt`.  

Неиспользуемые материалы старого 23-пунктового списка: `literature/archive/`.

## Структура

| Каталог | Содержимое |
|---------|------------|
| `literature/pdf/` | PDF, имя `NN_*.pdf` |
| `literature/segments/` | Выдержки, имя `NN_*.txt` |
| `literature/archive/` | Файлы, не входящие в список v6 |
| `literature/download_literature.sh` | Повторная загрузка по номерам статьи |

## Сводная таблица

| № | Источник | PDF | Сегмент | Примечание |
|---|----------|-----|---------|------------|
| 1 | ORB-SLAM3, TRO 2021 | `pdf/01_ORB-SLAM3.pdf` | `segments/01_ORB-SLAM3_abstract_intro.txt` | |
| 2 | VINS-Mono, TRO 2018 | `pdf/02_VINS-Mono.pdf` | `segments/02_VINS-Mono_abstract_intro.txt` | |
| 3 | ORB-SLAM2, TRO 2017 | `pdf/03_ORB-SLAM2.pdf` | `segments/03_ORB-SLAM2_abstract_intro.txt` | |
| 4 | OKVIS, IJRR 2015 | `pdf/04_OKVIS.pdf` | `segments/04_OKVIS_abstract_intro.txt` | |
| 5 | Preintegration, TRO 2017 | `pdf/05_Preintegration.pdf` | `segments/05_Preintegration_abstract_intro.txt` | |
| 6 | OpenVINS, ICRA 2020 | `pdf/06_OpenVINS.pdf` | `segments/06_OpenVINS_key.txt` | + Lee W. |
| 7 | Kim et al., IROS 2015 | — | `segments/07_Kim2015_bibliography.txt` | IEEE paywall |
| 8 | VPR-Bench, IJCV 2021 | `pdf/08_Zaffar_VPR-Bench.pdf` | `segments/08_Zaffar_abstract.txt` | |
| 9 | EuRoC, IJRR 2016 | — | `segments/09_EuRoC_abstract.txt` | SAGE |
| 10 | RANSAC, CACM 1981 | — | `segments/10_RANSAC_key.txt` | ACM |
| 11 | KITTI, CVPR 2012 | `pdf/11_KITTI.pdf` | `segments/11_KITTI_abstract.txt` | |
| 12 | TUM-VI, IJRR 2021 | `pdf/12_TUM-VI.pdf` | `segments/12_TUM-VI_abstract.txt` | |
| 13 | Бобков, Май, 2018 | `pdf/13_Bobkov2018.pdf` | `segments/13_Bobkov2018_key.txt` | |
| 14 | Голубков и др., 2026 | — | `segments/14_Golubkov2026_bibliography.txt` | журнал закрыт |
| 15 | Li & Mourikis, IJRR 2013 | `pdf/15_Li2013_MSCKF.pdf` | `segments/15_Li_MSCKF_consistency.txt` | PDF — слайды |
| 16 | Махмуд, Колюбин, 2026 | — | `segments/16_Mahmoud2026_bibliography.txt` | журнал закрыт |
| 17 | Ян Ган и др., 2023 | `pdf/17_YangGan_Gyroscopy2023.pdf` | `segments/17_YangGan_key.txt` | Дун Хоу-Го |
| 18 | SuperPoint, CVPRW 2018 | `pdf/18_SuperPoint.pdf` | `segments/18_SuperPoint_abstract.txt` | P. 224–236 |
| 19 | SuperGlue, CVPR 2020 | `pdf/19_SuperGlue.pdf` | `segments/19_SuperGlue_abstract.txt` | |
| 20 | Eigen et al., NIPS 2014 | `pdf/20_Eigen_Depth.pdf` | `segments/20_Eigen_depth_key.txt` | |
| 21 | DPT, ICCV 2021 | `pdf/21_DPT.pdf` | `segments/21_DPT_key.txt` | |
| 22 | AdaBins, CVPR 2021 | `pdf/22_AdaBins.pdf` | `segments/22_AdaBins_key.txt` | |
| 23 | DROID-SLAM, NeurIPS 2021 | `pdf/23_DROID-SLAM.pdf` | `segments/23_DROID-SLAM_abstract.txt` | P. 16558–16569 |
| 24 | Song et al., Sensors 2024 | — | `segments/24_Song2024_abstract_intro.txt` | MDPI 403 |
| 25 | Yang et al., Measurement 258 | — | `segments/25_Yang2026_bibliography.txt` | Elsevier |
| 26 | Huang et al., IJRR 2010 | `pdf/26_Huang2010_Observability.pdf` | `segments/26_Huang_observability_key.txt` | IJRR 29(5):502–528 |
| 27 | Сойфер, Гошин, 2025 | `pdf/27_Soifer2025.pdf` | `segments/27_Soifer2025_key.txt` | |

Прочерки у PDF: [7], [9], [10], [14], [16], [24], [25] — не дыры в нумерации, а отсутствующий полный текст.

## Архив (не в списке статьи)

| Файл | Почему в архиве |
|------|-----------------|
| `archive/pdf/09_Sun2017_substitute_VO_PartII.pdf` | Sun RSS 2017 не существует; заменён на [10] RANSAC |
| `archive/pdf/12_Brachmann_LessMore.pdf`, `12b_Brachmann_DSAC2017.pdf` | в тексте v6 нет ссылки |
| `archive/segments/19_Kim2021_bibliography.txt` | Kim RA-L 2021 заменён на [7] IROS 2015 |

## Повторная загрузка

```bash
bash literature/download_literature.sh
```

## Сверка 2026-08-20

Все PDF в `pdf/` — те же статьи, что в списке (нет подмен). Сегменты 01–27 полные.

В `Статья_v6.txt` убраны ложные привязки: §4.2 больше не цитирует [10, 24, 7] как описание skip MSCKF; §6.4 больше не цитирует [23, 25, 8] как подтверждение сдвига c(t). Эти номера остаются в обзоре, где они по теме.

На этап C: [1, 3] при f3 и [26, 15] при «покрытие/репроекция» — родственные, не буквальные источники формулы.
