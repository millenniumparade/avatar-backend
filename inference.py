@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        print("post")
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'})

        file = request.files['file']
        # check_and_clear_folders(folders_to_check)
        if file.filename == '':
            return jsonify({'error': 'No selected file'})

        if file and allowed_file(file.filename):
            timestamp = time.time()
            timestamp_i = int(timestamp)
            timestamp_f = str(timestamp - timestamp_i)
            Timestamp = str(timestamp_i) + timestamp_f[2:]
            s = time.time()
            # 将文件转换为jpg格式并保存为image.jpg
            save_as_jpg(file, Timestamp)
            preinputpath= os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'imageinput/image.jpg')
            preoutputpath= os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'imageprocess_1/imagecut.jpg')
            processed_image = process_image(device0, detector0, preinputpath, preoutputpath)
            p = time.time()
            print(s-p)
            s = time.time()
            parseinput_path = os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'imageprocess_1/')
            parseoutput_path = os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'parse/')
            parseoutput_path2 = os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'customhair/')
            parseoutput_path3 = os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'customglass/')
            ifglass, skin_color, hair_color = inference(modelfp, devicefp, parseinput_path, parseoutput_path, parseoutput_path2, parseoutput_path3)
            p = time.time()
            print(s-p)
            s = time.time()
            # genderpredict = predict_gender(preoutputpath, face_net, gender_net)

            input_folder = os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'imageprocess_1')
            output_folder = os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'test_results')
            drive_img_pil = fit(rigid_optimizer, nonrigid_optimizer, device, faceverse_model, faceverse_dict, g_detail, g_exp, version=1, input_folder=input_folder, res_folder=output_folder, save_ply=True, align=True)
            p = time.time()
            print(s-p)
            s = time.time()

            input_ply = os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'test_results/imagecut_base.ply')
            rotated_output_folder = os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'imageprocess_2')
            fvpoints = getpoints(input_ply, rotated_output_folder)
            # # 构建命令字符串
            # command = f"{script_path} {Timestamp}"

            # # 开启操作
            # result = subprocess.run(command, shell=True, capture_output=True, text=True)
            
            # # 输出脚本的标准输出和标准错误用于调试
            # print("stdout:", result.stdout)
            # print("stderr:", result.stderr)

            subprocess.call(['/bin/bash',"/home/ai_deploy/FaceVerse-main/run_commands_5003.sh", Timestamp])
            vertices_input = os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'imageinput/image.jpg')
            vertices_output = os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp)
            hairparsepath = os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'customhair/imagecut.png')
            glassparsepath = os.path.join('/home/ai_deploy/FaceVerse-main/imagesinput', Timestamp, 'customglass/imagecut.png')
            process_vertices(vertices_input, vertices_output, hairparsepath, glassparsepath, skin_color, hair_color, ifglass)
            p = time.time()
            print(s-p)
            # Read the HumanInfo.json file and return its content
            json_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'imagesinput', Timestamp, 'HumanInfo.json'))


            # ctpointspath = os.path.abspath(os.path.join(os.path.dirname(__file__), 'imagesinput', Timestamp, 'cartoon_model_points.npy'))

            # ct_points_dict = np.load(ctpointspath, allow_pickle=True).item()

            
            # ct_model_basic = ct_points_dict['basic']
            # ct_model_points = ct_points_dict['approximated']


            # img_io1 = io.BytesIO()
            # processed_image.save(img_io1, 'JPEG')
            # img_io1.seek(0)
            # img_base64_1 = base64.b64encode(img_io1.getvalue()).decode('utf-8')

            # img_io2 = io.BytesIO()
            # drive_img_pil.save(img_io2, 'JPEG')
            # img_io2.seek(0)
            # img_base64_2 = base64.b64encode(img_io2.getvalue()).decode('utf-8')

            response = send_file(json_file_path, as_attachment=True, download_name='HumanInfo.json')

            # response = {
            # 'processed_image': img_base64_1,
            # 'drive_img_pil': img_base64_2, 
            # 'fvpoints': fvpoints.tolist(),
            # 'ct_model_basic': ct_model_basic.tolist(),
            # 'ct_model_points': ct_model_points.tolist()
            # }
            
