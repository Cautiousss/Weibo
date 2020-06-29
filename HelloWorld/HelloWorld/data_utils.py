"""
crawl data
"""
import time
import codecs
import copy
import csv
import json
import os
import random
import re
import shutil
import sys
import traceback
from collections import OrderedDict
from datetime import date, datetime, timedelta
from time import sleep

from string import punctuation
import emoji
from collections import Counter

from dateutil.parser import parse
import requests
from absl import app, flags
from lxml import etree
from requests.adapters import HTTPAdapter
from tqdm import tqdm
import numpy as np
import jieba
from math import sqrt
from sklearn.externals import joblib
import jieba
from wordcloud import WordCloud
import matplotlib.font_manager as fm
from imageio import imread
from PIL import Image
import wordcloud

cookie = "_T_WM=78522337846; _WEIBO_UID=6338550883; ALF=1593420147; WEIBOCN_FROM=1110006030; SUBP=0033WrSXqPxfM725Ws9jqgMF55529P9D9WFh5n7HVJ-FC_saEzTIUpWT5JpX5K-hUgL.Foq0e0nfSK5R1he2dJLoIE-LxKBLB.2L12eLxKBLB.2L12eLxKBLB.2L12eLxKBLB.2L12Sh; SCF=ArjvLMxbY0E12ZIGg5Ml4_tjYAIWb20vYroqWzb1N4UacjgEEO_uBEpuja35r1KGEe_OKcN2AgVlKUy6Wm5GnOc.; SUB=_2A25z1m2gDeRhGeBN6FoU9S7Ewz-IHXVROXPorDV6PUJbktANLWrckW1NRGUWZDrJuznhlfpwY18qqax4Rr6jn_AF; SUHB=0sqxtPPVOJ2rQX; SSOLoginState=1590828528; XSRF-TOKEN=c3f14d; MLOGIN=1; M_WEIBOCN_PARAMS=luicode%3D10000011%26lfid%3D1076033864109310%26fid%3D1005053864109310%26uicode%3D10000011"


# 文本计算相关函数
def cos_sim(vector_a, vector_b):
    """
    计算两个向量之间的余弦相似度
    :param vector_a: 向量 a
    :param vector_b: 向量 b
    :return: sim
    """
    vector_a = np.mat(vector_a)
    vector_b = np.mat(vector_b)
    num = float(vector_a * vector_b.T)
    denom = np.linalg.norm(vector_a) * np.linalg.norm(vector_b)
    if denom==0:
        cos = 0
    else:
        cos = num / denom
    sim = 0.5 + 0.5 * cos

    return sim

def sentences_cos_sim(list_1,list_2):
    """ 计算两个文本之间的余弦相似度 """
    # 1.分词
    wb_1=[]
    wb_2=[]
    if type(list_1)==list:
        for sentence in list_1:
            seg_list=seg_sentence(sentence)
            wb_1=wb_1+seg_list
        for sentence in list_2:
            seg_list=seg_sentence(sentence)
            wb_2=wb_2+seg_list
    else:
        seg_list = seg_sentence(list_1)
        wb_1 = wb_1 + seg_list
        seg_list = seg_sentence(list_2)
        wb_2 = wb_2 + seg_list

    # 2.统计所有词组：
    wb = wb_1+wb_2
    wb=list(set(wb))

    # 3.获取词频：
    wb_1=Counter(wb_1)
    wb_2=Counter(wb_2)
    vec_1=[]
    vec_2=[]
    for w in wb:
        if wb_1.__contains__(w):
            vec_1.append(wb_1[w])
        else:
            vec_1.append(0)
    for w in wb:
        if wb_2.__contains__(w):
            vec_2.append(wb_2[w])
        else:
            vec_2.append(0)

    # 4.复杂度计算：
    ans = cos_sim(vec_1, vec_2)
    return ans


def one_day_sim(mylist):
    if len(mylist)<=1:
        return 0
    ans=0
    count=0
    for i in range(0,len(mylist)):
        for j in range(i+1,len(mylist)):
            count+=1
            ans+=sentences_cos_sim(mylist[i],mylist[j])
    return ans/count

# 对句子进行分词
def seg_sentence(sentence):
    # 去除emoji
    sentence = emoji.demojize(sentence)
    # 英文标点符号+中文标点符号
    punc = punctuation + u"., ;《》？！“”‘’@  # ￥%…&×（）——+【】{};；●，。&～、|\s:："
    sentence=re.sub(r"[{}]+".format(punc),"",sentence)
    # 分词
    sentence_seged = jieba.cut(sentence.strip())
    # 去除停用词
    outstr = []
    for word in sentence_seged:
        if word not in stopwords:
            if word != '\t':
                outstr.append(word)
    return outstr



class WeiboCrawler(object):
    def __init__(self,user_id):
        self.user_id = user_id

        self.followers_count = 100 #粉丝数，如果没有获取到默认爬100位
        self.follow_count = 100 #关注数，如果没有获取到默认爬100位

        self.follows_id = []
        self.follows = [] #关注的人=> 异常关注、沉寂关注
        self.fans_id = []
        self.fans = [] #粉丝集合，与follows一起计算互粉数
        self.weibos = [] #微博内容
        self.weibo_id_list = []
        self.follows_weibo = [] #关注的人的最近微博时间，判断是否是沉寂关注

        self.keywors = [] #根据微博内容统计关键字
        self.inactive_follows_id = []# 沉寂关注
        self.mutualFansNum = 0
        self.follow_id2weibo = {} # 粉丝的id到对应微博内容的对应
        self.follow_spammer = []

        self.red_v = 0 #关注的人中红V
        self.blue_v = 0 #关注的人中蓝V


    def getFollow(self):
        """ 爬取关注的人信息集合 """
        pages = (int)(self.follow_count/10)
        pages = min(pages,10)
        for i in range(pages+1):
            #微博用户关注列表JSON链接
            url = "https://m.weibo.cn/api/container/getSecond?containerid=100505{uid}_-_FOLLOWERS&page={page}".format(uid=self.user_id,page=i)
            try:
                req = requests.get(url)
                jsondata = req.text
                data = json.loads(jsondata)
                content = data["data"]['cards']
                #https://m.weibo.cn/api/container/getSecond?containerid=1005056338550883_-_FOLLOWERS&page=1
                for i in content:
                    id = i['user']['id'] #用户id
                    if id in self.follows_id:
                        continue
                    self.follows_id.append(id)
                    label = i['user']['screen_name'] #用户昵称
                    profile_url = i['user']['profile_image_url'] #头像的url，这样可以显示部分虚假用户的头像
                    gender = i['user']['gender'] #'f'女， 'm'男
                    descrip = i["desc1"]+i["desc2"]
                    weibo_num = i['user']['statuses_count']
                    fans_num, follow_num = i['user']['followers_count'], i['user']['follow_count']
                    verified = i['user']['verified']
                    urank = i['user']['urank']
                    mbrank = i['user']['mbrank']
                    if verified == True:
                        type = int(i['user']['verified_type'])
                        if type==0:
                            self.red_v +=1
                        else:
                            self.blue_v +=1
                    self.follows.append([id,label,profile_url,gender,descrip,weibo_num,fans_num,follow_num, verified, urank, mbrank])
            except Exception as e:
                return

    def getFans(self):
        """ 爬取粉丝的信息集合 """
        pages = (int)(self.followers_count/10)
        pages = min(pages,10)
        for i in range(pages+1):
            url = "https://m.weibo.cn/api/container/getSecond?containerid=100505{uid}_-_FANS&page={page}".format(uid=self.user_id,page=i)
            try:
                req = requests.get(url)
                jsondata = req.text
                data = json.loads(jsondata)
                content = data["data"]['cards']
                for i in content:
                    id = i['user']['id'] #用户id
                    if id in self.fans_id:
                        continue
                    self.fans_id.append(id)
                    label = i['user']['screen_name'] #用户昵称
                    profile_url = i['user']['profile_image_url'] #头像的url，这样可以显示部分虚假用户的头像
                    gender = i['user']['gender'] #'f'女， 'm'男
                    descrip = i["desc1"]+i["desc2"]
                    weibo_num = i['user']['statuses_count']
                    fans_num, follow_num = i['user']['followers_count'], i['user']['follow_count']
                    verified = i['user']['verified']
                    urank = i['user']['urank']
                    mbrank = i['user']['mbrank']
                    self.fans.append([id,label,profile_url,gender,descrip,weibo_num,fans_num,follow_num, verified, urank, mbrank])
            except Exception as e:
                return

    def computeMutualNum(self):
        """ 计算用户的互粉数目 """
        # 比较follows_id和fans_id的交集
        mutual_fans = (set(self.fans_id)&set(self.follows_id))
        self.mutualFansNum = len(mutual_fans)



    def handle_html(self, url):
        """ 处理html """
        try:
            html = requests.get(url,headers = {"Cookie":cookie}).content
            selector = etree.HTML(html)
            return selector
        except Exception as e:
            print('Error: ', e)

    def is_date(self, since_date):
        """ 判断日期格式是否正确 """
        try:
            if ':' in since_date:
                datetime.strptime(since_date, '%Y-%m-%d %H:%M')
            else:
                datetime.strptime(since_date, '%Y-%m-%d')
            return True
        except ValueError:
            return False

    def get_one_weibo(self,info):
        """ 获取一条微博的全部信息 """
        try:
            weibo_info = info['mblog']
            weibo_id = weibo_info['id']
            retweeted_status = weibo_info.get('retweeted_status')
            is_long = weibo_info.get('isLongText')
            if is_long:
                weibo = self.get_long_weibo(weibo_id)
                if not weibo:
                    weibo = self.parse_weibo(weibo_info)
            else:
                weibo = self.parse_weibo(weibo_info)
            weibo['retweet'] = True if retweeted_status else False
            weibo['created_at'] = self.standardize_date(weibo_info['created_at'])
            return weibo
        except Exception as e:
            print("Error: ",e)
            traceback.print_exc()

    def get_long_weibo(self,id):
        """ 获取长微博内容 """
        for i in range(5):
            url = 'https://m.weibo.cn/detail/%s' % id
            html = requests.get(url,headers = {"Cookie":cookie}).text
            html = html[html.find('"status":'):]
            html = html[:html.rfind('"hotScheme"')]
            html = html[:html.rfind(',')]
            html = '{' + html + '}'
            js = json.loads(html, strict=False)
            weibo_info = js.get('status')
            if weibo_info:
                weibo = self.parse_weibo(weibo_info)
                return weibo

    def standardize_date(self,created_at):
        """ 标准化微博发布时间 """
        if u"刚刚" in created_at:
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif u"分钟" in created_at:
            minute = created_at[:created_at.find(u"分钟")]
            minute = timedelta(minutes=int(minute))
            created_at = (datetime.now()-minute).strftime("%Y-%m-%d %H:%M:%S")
        elif u"小时" in created_at:
            hour = created_at[:created_at.find(u"小时")]
            hour = timedelta(hours=int(hour))
            created_at = (datetime.now() - hour).strftime("%Y-%m-%d %H:%M:%S")
        elif u"昨天" in created_at:
            day = timedelta(days=1)
            created_at = (datetime.now() - day).strftime("%Y-%m-%d %H:%M:%S")
        elif created_at.count('-') == 1:
            year = datetime.now().strftime("%Y")
            created_at = year + "-" + created_at
        return created_at

    def parse_weibo(self,weibo_info):
        weibo = {}
        if weibo_info['user']:
            weibo['user_id'] = weibo_info['user']['id']
            weibo['screen_name'] = weibo_info['user']['screen_name']
        else:
            weibo['user_id'] = ''
            weibo['screen_name'] = ''
        weibo['id'] = int(weibo_info['id'])
        weibo['bid'] = weibo_info['bid']
        text_body = weibo_info['text']
        selector = etree.HTML(text_body)
        weibo['text'] = etree.HTML(text_body).xpath('string(.)')
        weibo['length'] = len(weibo['text']) #长度

        # 是否含url
        urlRegex = re.compile(r"https?://")
        weibo['contrain_url'] = False
        if re.findall(urlRegex,weibo['text']):
            weibo['contrain_url'] = True

        weibo['attitudes_count'] = self.string2int(weibo_info.get('attitudes_count',0))
        weibo['comments_count'] = self.string2int(weibo_info.get('comments_count',0))
        weibo['reposts_count'] = self.string2int(weibo_info.get('reposts_count',0))
        return weibo

    def string2int(self,string):
        if isinstance(string,int):
            return string
        elif string.endswith(u'万+'):
            string = int(string[:-2]+'0000')
        elif string.endswith(u'万'):
            string = int(string[:-1]+'0000')
        return int(string)



    def getWeibos(self):
        """ 爬取用户的微博内容 """
        # 先爬最近的4页内容
        for page in range(3):
            params = {'containerid':'107603'+str(self.user_id),'page':page}
            url = "https://m.weibo.cn/api/container/getIndex?"
            try:
                r = requests.get(url,params=params,headers = {"Cookie":cookie})
                js = r.json()
                if js['ok']:
                    weibos = js['data']['cards']
                    for w in weibos:
                        if w['card_type']==9:
                            wb = self.get_one_weibo(w)
                            if wb:
                                if wb['id'] in self.weibo_id_list:
                                    continue
                                self.weibos.append(wb)
                                self.weibo_id_list.append(wb['id'])
            except Exception as e:
                print(e)

    def getKeyWords(self):
        """ 根据微博文本内容统计关键词 """
        text = ""
        for weibo in self.weibos:
            text+=weibo['text']

        segs = jieba.cut(text)

        wcdict = {}
        for word in segs:
            if len(word)==1:
                continue
            else:
                wcdict[word] = wcdict.get(word,0)+1
        wcls = list(wcdict.items())
        wcls.sort(key=lambda x:x[1],reverse=True)

        xx=['他们','没有','自己','一个','什么','这样','知道','我们','这个','这些','不过','已经','要是','觉得','那样','而且',"微博","转发","通过","现在","有人","时候"]

        for pair in wcls[:10]:
            if pair[0] not in xx:
                self.keywors.append(pair)
            # 生成词云
            jpg = imread('cc.jpg')
            mask = np.array(Image.open('cc.jpg'))
            image_colors = wordcloud.ImageColorGenerator(mask)
            text_list = []
            for seg in segs:
                if seg != "" and len(seg) != 1:
                    text_list.append(seg.replace(" ", ""))
            yc_text = ",".join(text_list)
            if len(yc_text) > 0:
                wc = WordCloud(background_color="white", max_words=200, min_font_size=10, max_font_size=35, width=400,
                               font_path="/Users/cautious/Downloads/msyh/msyh.ttf", mask=mask, color_func=image_colors)
                wc.generate(yc_text)
                file_path = self.user_id + "_yc" + ".png"
                wc.to_file(file_path)

    def get_inactive(self):

        """ 获取用户沉寂关注的集合 """
        for id in self.follows_id:
            screen_name = ' '
            params = {'containerid':'107603'+str(id),'page':0}
            url = "https://m.weibo.cn/api/container/getIndex?"
            try:
                lis = []
                r = requests.get(url,params=params,headers = {"Cookie":cookie})
                js = r.json()
                if js['ok']:
                    weibos = js['data']['cards']
                    flag = False
                    #print(weibos)
                    for w in weibos:  # 因为通常第一条微博是置顶，很可能不是近半年的。因此对第一页的微博分析，只要有时间在2020年，就不作为沉寂用户
                        if w['card_type']==9:
                            info = w['mblog']
                            create = self.standardize_date(info['created_at'])
                            time = create.split("-")[0]
                            if time=="2020":
                                flag = True
                            # 同时，我们读取该用户一页的微博内容
                            weibo = self.parse_weibo(info)
                            retweeted_status = info.get('retweeted_status')
                            weibo['retweet'] = True if retweeted_status else False #转发
                            weibo['created_at'] = create #发布时间
                            lis.append(weibo)
                            screen_name = weibo['screen_name']
                    if flag==False:
                        self.inactive_follows_id.append([id,screen_name])
                #if len(lis)>0:
                #    self.follow_id2weibo[id]=lis # 对该用户的一页微博内容进行保存
            except Exception as e:
                print("Error"+str(e))
                return

    def load_fans_weibo(self):
        """ 爬取粉丝的微博 """
        for id in self.fans_id:
            screen_name = ' '
            print("current searching id:"+str(id))
            params = {'containerid':'107603'+str(id),'page':0}
            url = "https://m.weibo.cn/api/container/getIndex?"
            try:
                lis = []
                r = requests.get(url,params=params,headers = {"Cookie":cookie})
                js = r.json()
                if js['ok']:
                    weibos = js['data']['cards']
                    #print(weibos)
                    for w in weibos:  # 因为通常第一条微博是置顶，很可能不是近半年的。因此对第一页的微博分析，只要有时间在2020年，就不作为沉寂用户
                        if w['card_type']==9:
                            info = w['mblog']
                            create = self.standardize_date(info['created_at'])
                            #我们读取该用户一页的微博内容
                            weibo = self.parse_weibo(info)
                            retweeted_status = info.get('retweeted_status')
                            weibo['retweet'] = True if retweeted_status else False #转发
                            weibo['created_at'] = create #发布时间
                            lis.append(weibo)
                            screen_name = weibo['screen_name']
                if len(lis)>0:
                    self.follow_id2weibo[id]=lis # 对该用户的一页微博内容进行保存
            except Exception as e:
                print("Error"+str(e))
                return


    def get_spammer(self):
        """ 统计异常关注 """
        self.load_fans_weibo()
        # self.fans.append([id,label,profile_url,gender,descrip,weibo_num,fans_num,follow_num, verified, urank, mbrank])
        for user in self.fans:
            dict = {}
            followee = int(user[7]) #F1 关注数
            follower = int(user[6]) #F2 粉丝数
            if follower==0:
                followee_follower_ration = 0
            else:
                followee_follower_ration = round(followee/follower,2) #F4关注数与粉丝数比值
            weibo = int(user[5]) #F7 微博数
            dict['id'] = user[0]
            dict['username'] = user[1]
            F1 = followee
            F2 = follower
            F4 = followee_follower_ration
            F7 = weibo


            if user[0] not in self.follow_id2weibo.keys():
                continue

            weibos = self.follow_id2weibo[user[0]] #该用户最近的微博

            # F9-时间间隔， F10-转发比， F11-url链接比，F12-微博评论比，F13-原创微博评论比，F14-微博平均长度，F15-微博余弦相似度, F16-模相似度
            origins , comments , origin_comments ,lens, total_len, contain_url_num = 0,0,0,0,len(weibos),0

            date_contents = {}

            for weibo in weibos:
                if weibo['retweet']==False:
                    origins+=1
                    origin_comments+=1
                if weibo['contrain_url']:
                    contain_url_num+=1
                day = weibo['created_at']
                if not date_contents.__contains__(day):
                    date_contents[day] = []
                date_contents[day].append(weibo['text']) # 为每一天的微博内容构建集合
                comments+=weibo['comments_count']
                lens+=weibo['length']
            if len(weibos)>=2:
                most_recent = parse(weibos[1]['created_at'])
            elif len(weibos)==1:
                most_recent = parse(weibos[0]['created_at'])
            else:
                most_recent = parse("2019-01-01")
            now=datetime.now()
            F9 = (now - most_recent).days

            F10 = round((total_len-origins)/total_len,2)
            F11 = round(contain_url_num/total_len,2)
            F12 = round(comments/total_len,2)
            if origins==0:
                F13=0
            else:
                F13 = round(origin_comments/origins,2)
            F14 = round(lens/total_len,2)

            # 计算微博内容余弦相似度
            mylist = []
            for date,content in date_contents.items():
                mylist.append(content)
            if len(mylist)>1:
                sum=0
                for i in range(len(mylist)-1):
                    sum += sentences_cos_sim(mylist[i],mylist[i+1])
                F15 = round(sum/(len(mylist)-1),2)
            else:
                F15=0
            sum=0
            for i in mylist:
                sum+=one_day_sim(i)
            F16 = round(sum/len(mylist),2)

            #一共有F1,F2,F4,F7,F9,F10,F11,F12,F13,F14,F15,F16
            #print(F1,F2,F4,F7,F9,F10,F11,F12,F13,F14,F15,F16)
            X = [[F1,F2,F4,F7,F9,F10,F11,F12,F13,F14,F15,F16]]
            X = np.array(X)
            X = np.nan_to_num(X)

            # 跑我们训练好的模型即可
            clf = joblib.load('RF.pkl')
            y_pred = clf.predict(X)
            print(user[1],"预测结果（0为正常用户，1为虚假用户)",y_pred[0])
            if y_pred[0]==1:
                self.follow_spammer.append([user[0],user[1]])

    def get_user_info(self):
        """ 获取用户的粉丝数，关注数 """
        params = {'containerid':'100505'+str(self.user_id)}
        url = "https://m.weibo.cn/api/container/getIndex?"
        try:
            r = requests.get(url,params=params,headers = {"Cookie":cookie})
            js = r.json()
            if js['ok']:
                info = js['data']['userInfo']
                self.followers_count = info.get('followers_count', 0)
                self.follow_count = info.get('follow_count', 0)
        except Exception as e:
            print(e)

    def computeFollowTextSim(self):
        """ 计算和用户微博内容相似度高的关注的人 """
        pass

    def verified_analysis(self):
        """ 计算关注的人中已经认证的 """
        pass


    def start(self):

        self.get_user_info()

        self.getFollow()
        self.getFans()
        self.computeMutualNum()
        self.getWeibos()
        self.getKeyWords()
        #print(self.keywors)
        self.get_inactive()


        try:
            self.get_spammer()
        except Exception as e:
            print("ERROR SPAMMER:"+str(e))


        # 展示结果的，可以全部注释
        print('='*50+"互相关注的用户:"+str(self.mutualFansNum)+'='*50)
        print( )
        print('='*50+"微博内容关键词"+'='*50)
        for keyword in self.keywors:
            print(keyword)
        print( )

        print('='*50+"沉寂关注"+'='*50)
        for user in self.inactive_follows_id:
            print(user)

        print( )

        print('='*50+"异常粉丝"+'='*50)
        for user in self.follow_spammer:
            print(user)

        print('='*50+"关注分布"+'='*50)
        print("红V与橙V数量:"+str(self.red_v))
        print("蓝V:"+str(self.blue_v))


if __name__ == "__main__":
    f = open("baidu_stopwords.txt","r")
    stopwords = {}.fromkeys(f.read().split("\n"))
    f.close()
    jieba.load_userdict("baidu_stopwords.txt")

    time_start=time.time()

    #wb = WeiboCrawler("6338550883")
    #wb = WeiboCrawler("5649502573")
    #wb = WeiboCrawler("1776448504")
    wb = WeiboCrawler("3227027755")
    wb.start()

    time_end=time.time()
    print('-'*120)
    print('Time Cost',time_end-time_start,'/s')


    """
    数据格式说明
      互相关注的用户数: wb.mutualFansNum  (int型)
      微博内容关键词: wb.keywors  (List型 ， (word, 次数),比如('爬山',4) )
      沉寂关注： wb.inactive_follows_id (List型， 每一个元素是[id,昵称]的形式, 比如[1740661795, '电影风中有朵雨做的云'] )
      异常粉丝:  wb.follow_spammer (List型， 每一个元素是[id,昵称]的形式, 比如[5675324903, 'DDuppp'])
      关注分布： 
          红V与橙V数量 ： wb.red_v int型
          蓝V: wb.blue_v int型
    """