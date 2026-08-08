conda install -c conda-forge dlib
pip install "setuptools<81"
pip install --no-build-isolation git+https://github.com/ageitgey/face_recognition_models
pip install face_recognition opencv-python numpy
curl -L -o models/deploy.prototxt https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt

curl -L -o models/res10_300x300_ssd_iter_140000.caffemodel https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel

for encyption - pip install cryptography


Password is stored as a salted PBKDF2-SHA256 hash (100,000 iterations)