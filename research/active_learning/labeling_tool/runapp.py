'''
runapp.py

Starts running a web application for labeling samples.
'''
import argparse, json, psycopg2, sys
import bottle
from peewee import *
sys.path.append('../../Database')
from DB_models import *

# webUIapp = bottle.Bottle()

#--------some stuff needed to get AJAX to work with bottle?--------#
def enable_cors():
    '''
    From https://gist.github.com/richard-flosi/3789163
    This globally enables Cross-Origin Resource Sharing (CORS) headers for every response from this server.
    '''
    bottle.response.headers['Access-Control-Allow-Origin'] = '*'
    bottle.response.headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
    bottle.response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'

def do_options():
    '''
    This seems necessary for CORS to work
    '''
    bottle.response.status = 204
    return



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run a web user interface for labeling camera trap images for classification.')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Web server host to bind to.')
    parser.add_argument('--port', type=int, default=8080, help='Web server port port to listen on.')
    parser.add_argument('--verbose', type=bool, default=True, help='Enable verbose debugging.')
    parser.add_argument('--db_name', type=str, default='missouricameratraps', help='Name of Postgres DB with target dataset tables.')
    parser.add_argument('--db_user', type=str, default=None, help='Name of user accessing Postgres DB.')
    parser.add_argument('--db_password', type=str, default=None, help='Password of user accessing Postgres DB.')
    args = parser.parse_args(sys.argv[1:])

    # Create a queue of images to pre-load

    # Create and set up a bottle application for the web UI
    webUIapp = bottle.Bottle()
    webUIapp.add_hook("after_request", enable_cors)
    webUIapp_server_kwargs = {
        "server": "tornado",
        "host": args.host,
        "port": args.port
    }
    ## static routes (to serve CSS, etc.)
    @webUIapp.route('/')
    def index():
        return bottle.static_file("index.html", root='static/html')
    
    @webUIapp.route('/favicon.ico')
    def favicon():
        return
    
    @webUIapp.route('/<filename:re:js\/.*>')
    def send_js(filename):
        return bottle.static_file(filename, root='static')
    
    @webUIapp.route('/<filename:re:css\/.*>')
    def send_css(filename):
        return bottle.static_file(filename, root='static')
    
    @webUIapp.route('/<filename:re:img\/placeholder.JPG>')
    def send_placeholder_image(filename):
        # print('trying to load image', filename)
        return bottle.static_file(filename, root='static')
    
    @webUIapp.route('/<filename:re:.*.JPG>')
    def send_image(filename):
        # print('trying to load camtrap image', filename)
        return bottle.static_file(filename, root='../../../../../../../../../.')
    
    # dynamic routes
    @webUIapp.route('/loadImages', method='POST')
    def load_images():
        data = bottle.request.json
        
        # # TODO: return file names of crops to show from "totag" csv or database
        DB_NAME = args.db_name
        USER = args.db_user
        PASSWORD = args.db_password
        #HOST = 'localhost'
        #PORT = 5432

        ## Try to connect as USER to database DB_NAME through peewee
        target_db = PostgresqlDatabase(DB_NAME, user=USER, password=PASSWORD, host='localhost')
        db_proxy.initialize(target_db)
        existing_image_entries = (Image
                                .select(Image.id, Image.file_name, Detection.kind, Detection.category)
                                .join(Detection, on=(Image.id == Detection.image))
                                .where((Image.grayscale == data['display_grayscale']) & (Detection.bbox_confidence >= data['detection_threshold']))
                                .order_by(fn.Random()).limit(data['num_images']))

        # for image_entry in existing_image_entries:
        data['display_images'] = {}
        data['display_images']['image_ids'] = [ie.id for ie in existing_image_entries]
        data['display_images']['image_file_names'] = [ie.file_name for ie in existing_image_entries]
        data['display_images']['detection_kinds'] = [ie.detection.kind for ie in existing_image_entries]
        data['display_images']['detection_categories'] = [str(ie.detection.category) for ie in existing_image_entries]

        bottle.response.content_type = 'application/json'
        bottle.response.status = 200
        return json.dumps(data)
    
    @webUIapp.route('/assignLabelDB', method='POST')
    def assign_label():
        data = bottle.request.json

        label_to_assign = data['label']
        label_category_name = label_to_assign.lower().replace(" ", "_")

        DB_NAME = args.db_name
        USER = args.db_user
        PASSWORD = args.db_password
        target_db = PostgresqlDatabase(DB_NAME, user=USER, password=PASSWORD, host='localhost')
        db_proxy.initialize(target_db)
        
        existing_category_entries = {cat.name: cat.id for cat in Category.select()}
        try:
            label_category_id = existing_category_entries[label_category_name]
        except:
            print('The label was not found in the database Category table')
            raise NotImplementedError

        images_to_label = [im['id'] for im in data['images']]
        ## NOTE: detection id (and image_id) are the same as image id in missouricameratraps_test
        matching_detection_entries = (Detection
                                .select(Detection.id, Detection.category_id)
                                .where((Detection.id << images_to_label))) # << means IN        
        for mde in matching_detection_entries:
            command = Detection.update(category_id=label_category_id, category_confidence=1, kind=4).where(Detection.id == mde.id)
            command.execute()


        bottle.response.content_type = 'application/json'
        bottle.response.status = 200
        return json.dumps(data)
    
    webUIapp.run(**webUIapp_server_kwargs)