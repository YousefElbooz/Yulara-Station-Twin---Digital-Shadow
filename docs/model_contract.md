# Model contract: الموديلات جوه التوأم

أي موديل بيدخل التوأم من خلال **adapter** بنفس الشكل (`backend/models/adapters.py`)، ومدخلاته من **نفس pipeline الفريق** (`backend/models/features.py`).

**الدليل إن الربط سليم:** كل موديل اتشغل من خلال الـ adapter، وطلّع نفس الـ test RMSE بتاع التدريب بالظبط، بفرق 0.0000 (`docs/model_comparison_2025.md`، الجزء 1).

## شروط عامة لكل الموديلات

| البند | القيمة |
|---|---|
| الملفات | `models_store/friend_v1/`، اتعملت بـ `scripts/train_friend_models.py` (نقل أمين لـ notebook الفريق، commit `2e63510`) |
| المخرج | قدرة AC للمحطة كلها، بالـ kW، ≥ 0، لكل خطوة 5 دقايق |
| الوقت | الـ timestamp هو آخر الـ 5 دقايق. الـ features بتتحسب بتوقيت المحطة المحلي (ACST)، وبتتحول لـ UTC في التوأم |
| الطقس | ERA5 لنقطة −25.24، 130.99، متحمّل بإعدادات الـ notebook (`data/era5/era5_hourly_site_utc.csv`)، ومتوزع على الـ 5 دقايق بطريقة الـ notebook (`interp`) |
| الناقص | بيتملا بالـ medians بتاعة التدريب (`train_median.json`) |
| التقسيم | تدريب 2016-04 → 2022-10، validation لحد 2024-07-25، test بعدها. **2025 ماحدش من الموديلات شافها في التدريب** |

## كل موديل

| المفتاح | الموديل | النوع | المدخلات | الملفات |
|---|---|---|---|---|
| `ridge` | Ridge regression | day-ahead | 71 feature (`feature_cols.txt`) | `ridge.pkl` |
| `random_forest` | Random forest | day-ahead | 71 | `random_forest.pkl` |
| `xgboost` | XGBoost | day-ahead | 71 | `xgboost.pkl` |
| `lightgbm` | LightGBM | day-ahead | 71 | `lightgbm.pkl` |
| `pinn_dayahead` | DP-PINN (CNN-LSTM) | day-ahead | 71، وبيبص على آخر 12 خطوة (ساعة) | `cnn_lstm_pinn_dayahead.pt` + `pinn_dayahead_x_scaler.pkl` |
| `lightgbm_nowcast` | LightGBM | nowcast | 76 (`feature_cols_nowcast.txt`) | `lightgbm_nowcast.pkl` |
| `pinn_nowcast` | DP-PINN (CNN-LSTM) | nowcast | 76، وآخر 12 خطوة | `cnn_lstm_pinn_nowcast.pt` + `pinn_x_scaler.pkl` |
| `stacking` | Ridge على 5 موديلات | nowcast | توقعات `random_forest` و `xgboost` و `lightgbm` و `lightgbm_nowcast` و `pinn_nowcast` | `stacking_meta.pkl` |

**النوعين:**
- **day-ahead:** بيستخدم الطقس + قدرة المحطة **نفس الوقت امبارح** (`Power_lag_288`).
- **nowcast:** بيستخدم كمان قدرة المحطة في **آخر ساعة** (`Power_lag_1` … `Power_lag_12`).

## ينفع لايف ولا لأ

| | replay على التاريخ (دلوقتي) | live (بعدين) |
|---|---|---|
| مدخلات الطقس | ERA5 | **ERA5 متأخر 5 أيام.** محتاج توقع طقس بنفس المتغيرات الـ 14، أو تدريب تاني على متغيرات التوقع |
| قدرة المحطة | من الملف | من بيانات DKASC اللايف |
| إزاي التوأم بياخدها | `data/clean/ml_predictions_5min.parquet` (محسوبة مرة واحدة بنفس الـ adapters) عن طريق `backend/models/hub.py` | الـ adapters تشتغل على آخر أسبوع بيانات (أطول feature محتاجة 7 أيام) |

## مشاكل معروفة
- **الـ PINN:** η و α لزقوا في حدودهم (0.35 و −0.001). الـ "physics judge" بيحكم بمعادلة مش مظبوطة (`docs/friend_repo_review.md`).
- **ERA5 في نفس اللحظة:** الـ day-ahead "توقع" بس بالاسم. ده مقبول للمقارنة، مش لتوقع حقيقي.
- **التقييد:** الموديلات اتعلمت تقليد التقييد. ده كويس لتوقع "المحطة هتطلّع كام"، وغلط لو السؤال "المحطة تقدر تطلّع كام".
